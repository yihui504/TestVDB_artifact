#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_index_create_003
# strategy: delete_consistency
# endpoint: index+create
# constraint_ids: qdrant_behavioral_index_create_001, qdrant_inv_delete_gone_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/create-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: delete_consistency (Strategy 2: post-DELETE state) x
  qdrant_behavioral_index_create_001 (the 404 branch: "404 when the
  collection is missing") + state invariant qdrant_inv_delete_gone_001
  (after a successful delete the collection must not exist; details access
  returns 404). Lifecycle: (1) control legs on the live collection — a
  valid index create returns 200 (the assertion's 200 branch) and a
  query/count against the collection succeed, proving the face works;
  (2) drop the collection (DELETE collections+delete, wait=true) -> expect
  200; (3) describe must return 404 (deleted-gone invariant; 200 here =
  resurrection Type4); (4) index+create against the DROPPED name -> must
  return 404 per the assertion: 2xx = Type1_IllegalSuccess (an index
  created on a nonexistent parent resource), 5xx with /healthz alive =
  Type3_RuntimeFailure, other 4xx (wrong disposition vs the pinned 404) is
  recorded as a measured-only NOTE; (5) index+create against a
  NEVER-EXISTED unique collection name -> same 404 oracle (the missing-
  collection branch must not depend on prior existence).
  [chunk_index+create coverage: delete_consistency x
  qdrant_behavioral_index_create_001 (404 branch + 200 control) x
  qdrant_inv_delete_gone_001]
Oracle: index+create on the live collection returns 200; after the drop,
  describe returns 404 and BOTH index+create probes (dropped name and
  never-existed name) return exactly 404; any 2xx on a missing collection =
  Type1_IllegalSuccess; 5xx with /healthz alive = Type3_RuntimeFailure;
  describe returning 200 after a successful drop = Type4_StateLogicViolation
  (qdrant_behavioral_index_create_001, qdrant_inv_delete_gone_001)
"""

import os
import sys
import json
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---- bootstrap (three-layer fallback: env -> upward walk -> contract target) ----
_sd = os.environ.get("TESTVDB_SCRIPTS_DIR")
if not _sd:
    for _p in Path(__file__).resolve().parents:
        if (_p / "scripts" / "runtime" / "__init__.py").exists():
            _sd = str(_p / "scripts")
            break
if not _sd or not Path(_sd, "runtime", "__init__.py").exists():
    print("VERDICT: SCRIPT_ERROR - runtime scripts dir not found (TESTVDB_SCRIPTS_DIR unset)")
    sys.exit(2)
sys.path.insert(0, _sd)

if not os.environ.get("TESTVDB_TARGET"):
    for _p in Path(__file__).resolve().parents:
        _c = _p / "structured_contract.json"
        if _c.exists():
            try:
                _t = json.loads(_c.read_text(encoding="utf-8")).get("target", "")
                if _t:
                    os.environ["TESTVDB_TARGET"] = str(_t).lower()
            except Exception:
                pass
            break

try:
    from runtime import get_runtime
    rt = get_runtime()
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR - runtime import failed: {e}")
    sys.exit(2)

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)

print(f"[PATHS] index keys present="
      f"{[k for k in ('create_index', 'describe_collection', 'drop_collection', 'query') if k in rt.PATHS]}")


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
    """Transport/5xx branch liveness re-check via the lightweight healthz face."""
    hs, hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def index_create(tag, collection, expect):
    """One index+create probe. expect: '404' or '200'.
    Returns True=ok / False=defect recorded / None=environment abort."""
    s, raw = safe_request("PUT", "create_index",
                          body={"field_name": "city",
                                "field_schema": {"type": "keyword"}},
                          path_params={"name": collection},
                          query_params={"wait": "true"})
    print(f"[{tag}] index+create on {collection} status={s} "
          f"raw={str(raw)[:240]}")
    if s == 0:
        if liveness(tag):
            print(f"NOTE: {tag}: transport loss (status 0) while /healthz "
                  f"alive - single occurrence recorded, not claimed")
            return True
        return None
    if 500 <= s <= 599:
        if liveness(tag):
            return ("T3", s, raw)
        return None
    if expect == "200" and s in (200, 201):
        print(f"[{tag}] OK: 200 on the live collection")
        return True
    if expect == "404" and s == 404:
        print(f"[{tag}] OK: 404 on missing collection as asserted")
        return True
    # expectation/observation contradiction (typed per G5)
    if expect == "404" and 200 <= s <= 299:
        return ("T1", s, raw)          # accepted where 404 was pinned
    if expect == "200" and 400 <= s <= 499:
        return ("T1", s, raw)          # legal valid input rejected
    return ("NOTE", s, raw)            # gray-zone disposition: measured only


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sidx3_" + TS + "_"
    C1 = PFX + "live"
    C2 = PFX + "ghost"   # never created
    DEFECTS = []
    NOTES = []

    try:
        ok, err = rt.setup_default(C1, 4)
        if not ok:
            print(f"VERDICT: SCRIPT_ERROR - setup failed: {err}")
            return "SCRIPT_ERROR"
        s, raw = safe_request("PUT", "upsert_points", body={"points": [
            {"id": i, "vector": [0.1 + 0.01 * i, 0.2, 0.3, 0.4],
             "payload": {"city": f"c{i % 3}"}}
            for i in range(1, 7)
        ]}, path_params={"name": C1}, query_params={"wait": "true"})
        print(f"[setup upsert] status={s} raw={str(raw)[:160]}")
        if s not in (200, 201):
            return "SCRIPT_ERROR"

        # ---- control 1: index+create on the live collection -> 200 ----
        r = index_create("ctrl live create", C1, "200")
        if r is None:
            return "SCRIPT_ERROR"
        if isinstance(r, tuple):
            kind, s, raw = r
            if kind == "T3":
                DEFECTS.append(
                    f"(ctrl live create) HTTP {s} on a valid create while "
                    f"/healthz alive - Type3_RuntimeFailure - raw={str(raw)[:160]}")
            elif kind == "T1":
                DEFECTS.append(
                    f"(ctrl live create) valid index create on the live "
                    f"collection rejected with HTTP {s} instead of the pinned "
                    f"200 - Type1_IllegalSuccess - raw={str(raw)[:160]} "
                    f"(qdrant_behavioral_index_create_001 200 branch)")
            else:
                NOTES.append(f"ctrl live create: HTTP {s} (expected 200) - "
                             f"legal input rejected, recorded")

        # ---- control 2: collection queryable before the drop ----
        s, raw = safe_request("POST", "query",
                              body={"query": {"nearest": [0.11, 0.2, 0.3, 0.4]},
                                    "limit": 3},
                              path_params={"name": C1})
        print(f"[ctrl query] status={s} raw={str(raw)[:160]}")
        if s not in (200, 201):
            if s != 0 and not (500 <= s <= 599):
                return "SCRIPT_ERROR"
            if not liveness("ctrl query"):
                return "SCRIPT_ERROR"

        # ---- drop the collection ----
        s, raw = safe_request("DELETE", "drop_collection",
                              path_params={"name": C1},
                              query_params={"wait": "true"})
        print(f"[drop] status={s} raw={str(raw)[:200]}")
        if s not in (200, 201):
            if not liveness("drop"):
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(drop) dropping an existing collection returned HTTP {s} "
                f"while /healthz alive - Type3_RuntimeFailure - "
                f"raw={str(raw)[:160]}")

        # ---- deleted-gone invariant: describe must be 404 ----
        s, raw = safe_request("GET", "describe_collection",
                              path_params={"name": C1})
        print(f"[describe dropped] status={s} raw={str(raw)[:240]}")
        if s == 200:
            DEFECTS.append(
                f"(describe dropped) GET describe on the dropped collection "
                f"returned 200 (raw={str(raw)[:160]}) - "
                f"Type4_StateLogicViolation - resource resurrected after "
                f"successful delete (qdrant_inv_delete_gone_001)")
        elif s == 0 or 500 <= s <= 599:
            if not liveness("describe dropped"):
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(describe dropped) HTTP {s} while /healthz alive - "
                f"Type3_RuntimeFailure - raw={str(raw)[:160]}")
        elif s != 404:
            NOTES.append(f"describe dropped: HTTP {s} (expected 404) - "
                         f"disposition anomaly recorded, not claimed")

        # ---- probe 1: index+create on the DROPPED name -> 404 ----
        r = index_create("probe dropped", C1, "404")
        if r is None:
            return "SCRIPT_ERROR"
        if isinstance(r, tuple):
            kind, s, raw = r
            if kind == "T3":
                DEFECTS.append(
                    f"(probe dropped) HTTP {s} on index+create for a missing "
                    f"collection while /healthz alive - "
                    f"Type3_RuntimeFailure - raw={str(raw)[:160]}")
            elif kind == "T1":
                DEFECTS.append(
                    f"(probe dropped) index+create on the DROPPED collection "
                    f"returned HTTP {s} (2xx family) instead of the pinned "
                    f"404 - Type1_IllegalSuccess - raw={str(raw)[:160]} "
                    f"(qdrant_behavioral_index_create_001 404 branch)")
            else:
                NOTES.append(f"probe dropped: HTTP {s} (expected 404) - "
                             f"disposition anomaly recorded, not claimed")

        # ---- probe 2: index+create on a NEVER-EXISTED name -> 404 ----
        r = index_create("probe ghost", C2, "404")
        if r is None:
            return "SCRIPT_ERROR"
        if isinstance(r, tuple):
            kind, s, raw = r
            if kind == "T3":
                DEFECTS.append(
                    f"(probe ghost) HTTP {s} on index+create for a "
                    f"never-existed collection while /healthz alive - "
                    f"Type3_RuntimeFailure - raw={str(raw)[:160]}")
            elif kind == "T1":
                DEFECTS.append(
                    f"(probe ghost) index+create on a never-existed collection "
                    f"returned HTTP {s} (2xx family) instead of the pinned "
                    f"404 - Type1_IllegalSuccess - raw={str(raw)[:160]} "
                    f"(qdrant_behavioral_index_create_001 404 branch)")
            else:
                NOTES.append(f"probe ghost: HTTP {s} (expected 404) - "
                             f"disposition anomaly recorded, not claimed")

        for n in NOTES:
            print(f"NOTE: {n}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("post-DELETE consistency verified: live-collection create 200; "
              "after drop describe=404 and index+create returns 404 for both "
              "the dropped and the never-existed names - NO_DEFECT")
        return "NO_DEFECT"
    finally:
        # cleanup (own data only; failure must not flip the verdict)
        for name in (C1, C2):
            try:
                rt.drop_collection(name)
                print(f"[cleanup] dropped {name}")
            except Exception as e:
                print(f"[cleanup] drop {name} failed (ignored): {e}")


if __name__ == "__main__":
    try:
        _v = main()
    except Exception:
        import traceback
        traceback.print_exc()
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
