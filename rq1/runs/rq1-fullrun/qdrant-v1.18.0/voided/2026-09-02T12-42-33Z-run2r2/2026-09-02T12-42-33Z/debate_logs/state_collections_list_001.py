#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_list_001
# strategy: count_consistency
# endpoint: collections+list
# constraint_ids: qdrant_behavioral_collections_list_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collections
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 1 (CRUD-then-COUNT) executed through the global LIST
  face (collections+list; runtime PATHS list_collections = /collections,
  verbatim raw_knowledge api_endpoints[].url).
  qdrant_behavioral_collections_list_001 pins the face: HTTP 200 whose
  body carries the CollectionsResponse envelope result.collections[] --
  an array of {name} CollectionDescription entries. NOTE: the
  materialized response_shape grid on this endpoint is a describe-shaped
  openapi (mechanical backfill) artifact; the assertion + the published
  v1.18.x OpenAPI CollectionsResponse agree on result.collections[],
  and that agreement is the oracle here.
  (A positive shape) create K=3 uniquely-prefixed collections ->
      GET /collections is exactly 200, result is an object,
      result.collections is a JSON array, and EVERY entry is an object
      carrying a non-empty string name (global-face discipline: shape
      is judged on all entries, membership is PREFIX-FILTERED --
      sibling collections from other scripts are tolerated).
  (B count consistency) all K prefixed names present, each EXACTLY
      once -- the registry must track successful creates; a missing
      name or a duplicated entry = state disagrees with stored reality.
  (C data-op stability) upsert N=5 points (wait=true) into one of
      them -> list still shows that name exactly once (the name
      registry must be unaffected by point traffic).
  (D delete leg) DELETE one of them (200-confirmed) -> list converges
      to the surviving K-1 prefixed names with the deleted name absent
      (bounded retry; persistent presence = zombie entry). Mirrors
      qdrant_inv_delete_gone_001's "absent from the list" leg, judged
      through THIS chunk's face.
  [chunk_collections+list coverage: count_consistency x
   qdrant_behavioral_collections_list_001 (200/array/{name} envelope
   shape + create/delete membership tracking + point-traffic stability
   through the list face)]
Oracle: GET /collections returns exactly 200 with result.collections a
  JSON array whose entries all carry a non-empty string name; after
  K=3 successful prefixed creates all K names appear exactly once
  (missing or duplicated = Type4_StateLogicViolation); after a
  wait-confirmed point upsert the name still appears exactly once;
  after a 200-confirmed DELETE of one name the list converges within
  bounded retries to K-1 prefixed names with the deleted name absent
  (persistent presence = Type4 zombie); non-200 on the list face with
  /healthz alive = Type4; 5xx with /healthz alive =
  Type3_RuntimeFailure.
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

DIM = 4
K = 3
NPTS = 5


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def parse_json(raw):
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return b if isinstance(b, dict) else None


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scl1_" + TS + "_"
    NAMES = [PFX + f"c{i}" for i in range(K)]
    DEFECTS = []

    def alive():
        _hs, _hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[healthz] status={_hs} raw={str(_hraw)[:120]}")
        return _hs == 200

    def list_face(tag):
        """One list call: transport/5xx/non-200/shape triage.
        Returns ('OK', names) / ('BAD', None) / ('ERR', None)."""
        s, raw = safe_request("GET", "list_collections")
        print(f"[list#{tag}] status={s} raw={str(raw)[:240]}")
        if s == 0:
            alive()
            return "ERR", None
        if 500 <= s <= 599:
            if alive():
                DEFECTS.append(f"list#{tag} returned {s} with service alive — "
                               f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
            else:
                return "ERR", None
            return "BAD", None
        if s != 200:
            if alive():
                DEFECTS.append(f"list#{tag} returned {s} (assertion pins 200 + "
                               f"result.collections[] array) — "
                               f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
            else:
                return "ERR", None
            return "BAD", None
        b = parse_json(raw)
        res = b.get("result") if isinstance(b, dict) else None
        cols = res.get("collections") if isinstance(res, dict) else None
        if not isinstance(cols, list):
            DEFECTS.append(f"list#{tag} 200 body lacks the result.collections "
                           f"array (assertion: array of {{name}} entries) — "
                           f"Type4_StateLogicViolation — raw={str(raw)[:200]} "
                           f"(qdrant_behavioral_collections_list_001)")
            return "BAD", None
        names = []
        bad = 0
        for e in cols:
            if isinstance(e, dict) and isinstance(e.get("name"), str) and e["name"]:
                names.append(e["name"])
            else:
                bad += 1
        if bad:
            DEFECTS.append(f"list#{tag}: {bad} entries in result.collections "
                           f"carry no non-empty string name (assertion: array "
                           f"of {{name}} CollectionDescription entries) — "
                           f"Type4_StateLogicViolation")
        return "OK", names

    def list_until(tag, pred, attempts=4, delay=0.5):
        """Bounded convergence: returns ('OK'|'NO'|'ERR', last_names)."""
        names = None
        for i in range(attempts):
            st, names = list_face(f"{tag}.{i}")
            if st == "ERR":
                return "ERR", None
            if st == "OK" and pred(names):
                return "OK", names
            if st == "OK":
                mine = [n for n in names if n.startswith(PFX)]
                print(f"[list_until#{tag}.{i}] not yet satisfied; "
                      f"prefixed entries={len(mine)}")
            if i < attempts - 1:
                time.sleep(delay)
        return "NO", names

    def dupes_of(names):
        mine = [n for n in names if isinstance(n, str) and n.startswith(PFX)]
        return sorted({n for n in mine if mine.count(n) > 1})

    try:
        # ---- (A/B) create K prefixed collections, then list ----
        for n in NAMES:
            ok, err = rt.setup_default(n, DIM, "Cosine")
            if not ok:
                print(f"SETUP_FAIL: create {n} {err}")
                return "SCRIPT_ERROR"
        survivors = list(NAMES)

        st, names = list_until("A", lambda ns: all(n in ns for n in NAMES))
        if st == "ERR":
            return "SCRIPT_ERROR"
        if st == "NO":
            missing = [n for n in NAMES if n not in (names or [])]
            DEFECTS.append(f"after {K} successful creates the list face is "
                           f"missing {missing} (expected all of {NAMES}) — "
                           f"registry disagrees with stored state — "
                           f"Type4_StateLogicViolation "
                           f"(qdrant_behavioral_collections_list_001)")
        else:
            d = dupes_of(names)
            if d:
                DEFECTS.append(f"prefixed names duplicated in result.collections: "
                               f"{d} (each created collection must appear exactly "
                               f"once) — Type4_StateLogicViolation")

        # ---- (C) point traffic must not disturb the name registry ----
        target = NAMES[0]
        pts = [{"id": i, "vector": [0.05 * (i + 1)] * DIM} for i in range(NPTS)]
        s, raw = safe_request("PUT", "upsert_points", {"points": pts},
                              path_params={"name": target},
                              query_params={"wait": "true"})
        print(f"[upsert x{NPTS} -> {target}] status={s} raw={str(raw)[:160]}")
        if s != 200:
            print(f"SETUP_FAIL: upsert {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"
        st, names = list_until("C", lambda ns: isinstance(ns, list)
                               and ns.count(target) == 1)
        if st == "ERR":
            return "SCRIPT_ERROR"
        if st == "NO":
            cnt = (names or []).count(target)
            DEFECTS.append(f"after a wait=true upsert of {NPTS} points the list "
                           f"face shows {target} {cnt} times (expected exactly "
                           f"1) — Type4_StateLogicViolation")
        else:
            d = dupes_of(names)
            if d:
                DEFECTS.append(f"prefixed names duplicated after point traffic: "
                               f"{d} — Type4_StateLogicViolation")

        # ---- (D) 200-confirmed delete -> list converges without the name ----
        victim = NAMES[1]
        s, raw = safe_request("DELETE", "drop_collection",
                              path_params={"name": victim},
                              query_params={"timeout": "30"})
        print(f"[delete {victim}] status={s} raw={str(raw)[:160]}")
        if s != 200:
            print(f"SETUP_FAIL: delete {victim} returned {s} (its own face is "
                  f"the delete chunk's unit; here it is a state transition)")
            return "SCRIPT_ERROR"
        survivors = [n for n in NAMES if n != victim]

        st, names = list_until("D", lambda ns: victim not in ns
                               and all(n in ns for n in survivors))
        if st == "ERR":
            return "SCRIPT_ERROR"
        if st == "NO":
            zs = [n for n in (names or []) if n == victim]
            miss = [n for n in survivors if n not in (names or [])]
            detail = []
            if zs:
                detail.append(f"zombie entry {victim} persists after 200-delete "
                              f"+ retries")
            if miss:
                detail.append(f"survivors missing from list: {miss}")
            DEFECTS.append("; ".join(detail) + " — Type4_StateLogicViolation "
                           f"(qdrant_behavioral_collections_list_001, mirrors "
                           f"qdrant_inv_delete_gone_001 absence leg)")
        else:
            d = dupes_of(names)
            if d:
                DEFECTS.append(f"prefixed names duplicated after delete: {d} — "
                               f"Type4_StateLogicViolation")

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        for n in NAMES:
            try:
                rt.drop_collection(n)
            except Exception:
                pass


if __name__ == "__main__":
    try:
        _v = main()
    except Exception:
        import traceback
        traceback.print_exc()
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
