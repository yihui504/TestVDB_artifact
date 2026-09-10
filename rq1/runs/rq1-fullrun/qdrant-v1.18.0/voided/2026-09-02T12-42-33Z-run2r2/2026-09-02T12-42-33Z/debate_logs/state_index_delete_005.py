#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_index_delete_005
# strategy: delete_consistency
# endpoint: index+delete
# constraint_ids: qdrant_behavioral_index_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/delete-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: delete_consistency (Strategy 2: post-DELETE consistency, HTTP status
  face) x qdrant_behavioral_index_delete_001 ("index deletion (existing or
  not) returns HTTP 200; missing collection returns 404"). The full status
  matrix of DELETE /collections/{name}/index/{field}:
  (1) existing index on a live collection -> 200;
  (2) non-existent index (field absent from every payload) on a live
      collection -> 200;
  (3) never-created collection name (unique prefix, guaranteed 404 leg) ->
      404;
  (4) a collection that was live, carried a REAL index, and was then dropped
      -> index delete must return 404 (the dropped-collection face of the
      404 clause, checked twice for 404 stability).
  Response envelopes of the 200 legs are printed and cross-checked against
  the contract response_shape (top-level status:string, result:object) as
  observations; adjudication keys on the HTTP status code.
  [chunk_index+delete coverage: delete_consistency x
  qdrant_behavioral_index_delete_001 (all four status faces: existing 200,
  non-existent 200, never-created 404, dropped-collection 404 x2)]
Oracle: legs (1) and (2) return exactly 200 (2xx) on the live collection;
legs (3) and (4) return exactly 404, and the 404 is stable on repeat; a 2xx
  on the never-created or dropped collection = Type1_IllegalSuccess (index
  delete succeeded against nothing); a 4xx (404/409/...) on the live
  collection legs = violating the documented 200 promise =
  Type4_StateLogicViolation status-contract face; 5xx/transport while
  /healthz alive = Type3_RuntimeFailure (qdrant_behavioral_index_delete_001)
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
      f"{[k for k in ('delete_index', 'create_index', 'describe_collection', 'drop_collection', 'create_collection') if k in rt.PATHS]}")


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
    hs, hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def parse_json(raw):
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return b if isinstance(b, dict) else None


def observe_envelope(tag, raw):
    """Print-only shape observation vs contract response_shape
    (status: string, result: object); not a defect trigger by itself."""
    b = parse_json(raw)
    if b is None:
        print(f"[{tag}] envelope note: body not a JSON object: {str(raw)[:120]}")
        return
    status_f = b.get("status")
    result_f = b.get("result")
    ok_shape = (isinstance(status_f, str) and status_f == "ok"
                and isinstance(result_f, dict))
    print(f"[{tag}] envelope note: status={status_f!r} "
          f"result_type={type(result_f).__name__} "
          f"shape_matches_response_shape={ok_shape}")


def adjudicate(tag, s, raw, want_2xx, DEFECTS):
    """want_2xx=True: promise is 200 (existing collection, index or not).
    want_2xx=False: promise is 404 (missing collection)."""
    print(f"[{tag}] status={s} raw={str(raw)[:220]}")
    if s == 0:
        if liveness(tag):
            DEFECTS.append(
                f"({tag}) transport loss (status 0) while /healthz alive - "
                f"Type3_RuntimeFailure - raw={str(raw)[:160]}")
        else:
            return "DEAD"
        return "OK"
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(
                f"({tag}) HTTP {s} while /healthz alive - "
                f"Type3_RuntimeFailure - raw={str(raw)[:160]}")
        else:
            return "DEAD"
        return "OK"
    if want_2xx:
        if 200 <= s <= 299:
            observe_envelope(tag, raw)
            return "OK"
        DEFECTS.append(
            f"({tag}) index delete on a live collection returned HTTP {s}; "
            f"the documented promise is 200 whether or not the index "
            f"exists - Type4_StateLogicViolation (status-contract face) - "
            f"raw={str(raw)[:160]} (qdrant_behavioral_index_delete_001)")
        return "OK"
    # promise: 404
    if s == 404:
        return "OK"
    if 200 <= s <= 299:
        DEFECTS.append(
            f"({tag}) index delete returned HTTP {s} against a missing "
            f"collection (success against nothing) - Type1_IllegalSuccess - "
            f"raw={str(raw)[:160]} (qdrant_behavioral_index_delete_001)")
    else:
        DEFECTS.append(
            f"({tag}) index delete against a missing collection returned "
            f"HTTP {s}; expected 404 - Type4_StateLogicViolation "
            f"(status-contract face) - raw={str(raw)[:160]}")
    return "OK"


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sidd5_" + TS + "_"
    C1 = PFX + "col"
    C2 = PFX + "dropped"
    GHOST = PFX + "never_created"
    DEFECTS = []

    pts = [{"id": i, "vector": [0.1, 0.2, 0.3, 0.4],
            "payload": {"f_kw": f"kw{i % 2}"}} for i in range(1, 4)]

    try:
        # ---- setup: C1 live with a REAL index; C2 live, indexed, then dropped ----
        for c in (C1, C2):
            ok, err = rt.setup_default(c, 4)
            if not ok:
                print(f"VERDICT: SCRIPT_ERROR - setup {c} failed: {err}")
                return "SCRIPT_ERROR"
        s, raw = safe_request("PUT", "upsert_points", body={"points": pts},
                              path_params={"name": C1},
                              query_params={"wait": "true"})
        print(f"[setup upsert C1] status={s} raw={str(raw)[:160]}")
        if s not in (200, 201):
            return "SCRIPT_ERROR"
        for c in (C1, C2):
            s, raw = safe_request("PUT", "create_index",
                                  body={"field_name": "f_kw",
                                        "field_schema": {"type": "keyword"}},
                                  path_params={"name": c},
                                  query_params={"wait": "true"})
            print(f"[setup create index {c}] status={s} raw={str(raw)[:160]}")
            if s not in (200, 201):
                return "SCRIPT_ERROR"

        # drop C2 now (the dropped-collection face of the 404 clause)
        s, raw = safe_request("DELETE", "drop_collection",
                              path_params={"name": C2})
        print(f"[setup drop C2] status={s} raw={str(raw)[:160]}")
        if s not in (200, 201):
            print("VERDICT: SCRIPT_ERROR - could not drop C2 for the "
                  "dropped-collection leg")
            return "SCRIPT_ERROR"

        # ---- leg 1: existing index on live C1 -> 200 ----
        r1 = adjudicate("leg1 existing-index delete", *safe_request(
            "DELETE", "delete_index",
            path_params={"name": C1, "field_name": "f_kw"},
            query_params={"wait": "true"}), True, DEFECTS)
        if r1 == "DEAD":
            return "SCRIPT_ERROR"

        # ---- leg 2: non-existent index on live C1 -> 200 ----
        r2 = adjudicate("leg2 nonexistent-index delete", *safe_request(
            "DELETE", "delete_index",
            path_params={"name": C1, "field_name": "f_ghost_never_indexed"},
            query_params={"wait": "true"}), True, DEFECTS)
        if r2 == "DEAD":
            return "SCRIPT_ERROR"

        # ---- leg 3: never-created collection -> 404 ----
        r3 = adjudicate("leg3 never-created collection", *safe_request(
            "DELETE", "delete_index",
            path_params={"name": GHOST, "field_name": "f_kw"},
            query_params={"wait": "true"}), False, DEFECTS)
        if r3 == "DEAD":
            return "SCRIPT_ERROR"

        # ---- leg 4a/4b: dropped collection -> 404, stable on repeat ----
        r4 = adjudicate("leg4a dropped collection", *safe_request(
            "DELETE", "delete_index",
            path_params={"name": C2, "field_name": "f_kw"},
            query_params={"wait": "true"}), False, DEFECTS)
        if r4 == "DEAD":
            return "SCRIPT_ERROR"
        r5 = adjudicate("leg4b dropped collection repeat", *safe_request(
            "DELETE", "delete_index",
            path_params={"name": C2, "field_name": "f_kw"},
            query_params={"wait": "true"}), False, DEFECTS)
        if r5 == "DEAD":
            return "SCRIPT_ERROR"

        # ---- control: C1 still fully alive after its index deletion ----
        s, raw = safe_request("POST", "count", body={"exact": True},
                              path_params={"name": C1})
        print(f"[control count C1] status={s} raw={str(raw)[:160]}")
        b = parse_json(raw)
        cnt = None
        if s == 200 and b and isinstance(b.get("result"), dict):
            cnt = b["result"].get("count")
        if s != 200 or cnt != 3:
            DEFECTS.append(
                f"(control) C1 exact count after index deletion = {cnt} "
                f"(status {s}), expected 3 - Type4_StateLogicViolation - "
                f"index deletion must not delete data")

        # ---- summary ----
        print(f"[summary] legs adjudicated: existing/nonexistent on live col "
              f"(want 200), never-created + dropped x2 (want 404); "
              f"control_count={cnt} defects={len(DEFECTS)}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("status matrix clean: live-collection deletes 200 (existing and "
              "non-existent index alike), never-created and dropped "
              "collection deletes 404 stable on repeat, data intact - "
              "NO_DEFECT")
        return "NO_DEFECT"
    finally:
        # cleanup (own data only; failure must not flip the verdict)
        for c in (C1, C2):
            try:
                rt.drop_collection(c)
                print(f"[cleanup] dropped {c}")
            except Exception as e:
                print(f"[cleanup] drop {c} failed (ignored): {e}")


if __name__ == "__main__":
    try:
        _v = main()
    except Exception:
        import traceback
        traceback.print_exc()
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
