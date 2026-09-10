#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_query_batch_missing404_001
# strategy: delete_consistency
# endpoint: points+query+batch
# constraint_ids: qdrant_behavioral_points_query_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/batch-query
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: collection-level post-DELETE consistency of the batch query face
  (Strategy 2: post-DELETE consistency) x
  qdrant_behavioral_points_query_batch_001, whose expected_behavior PINS
  two dispositions: "HTTP 200 with one result per search in the same
  order" and "missing collection returns 404". Legs:
  (neg1) batch query (valid searches) against a NEVER-CREATED collection
  -> must be exactly 404 (the pinned missing-collection disposition);
  200 = fabricated empty results for a nonexistent collection,
  4xx-other = disposition contradicts the pinned 404 (Type4), 5xx with
  /healthz alive = Type3.
  (pos) create the collection -> the IDENTICAL batch body must flip to
  200 with len(result) == len(searches) and each entry an object whose
  "points" is a list (response_shape grid: result array; result[] object;
  result[].points array) — positive pairing so the 404 claim is not
  groundless (G4).
  (neg2) DELETE the collection -> the identical batch body must return
  404 again (post-delete gone; corroborates qdrant_inv_delete_gone_001:
  deleted collection's data faces must refuse, not serve).
  Searches are nearest-only on purpose: by-id searches on an empty
  collection legitimately 4xx (R39 adjudication), which would contaminate
  the disposition legs; nearest queries on an empty-but-existing
  collection are the clean 200-with-empty-points case.
  [chunk_points+query+batch coverage: delete_consistency x
  qdrant_behavioral_points_query_batch_001 (never-created 404 +
  created-200 positive control + post-delete 404 on the identical body)]
Oracle: never-created collection -> batch query returns HTTP 404 (200 or
  any non-404 = Type4_StateLogicViolation against the pinned promise);
  created -> 200 with len(result) == 2, entries objects with points lists;
  after DELETE -> 404 again on the identical body (non-404 = Type4);
  5xx legs require /healthz liveness re-check before any verdict
  (alive = Type3_RuntimeFailure, dead = SCRIPT_ERROR); transport failure
  -> liveness re-check before any verdict.
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

# URLs registered VERBATIM from raw_knowledge api_endpoints[]:
#   {"path": "points+query+batch", "method": "POST",
#    "url": "/collections/{collection_name}/points/query/batch"}
rt.PATHS["query_batch"] = "/collections/{collection_name}/points/query/batch"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if k in ('query_batch', 'create_collection', 'drop_collection', 'healthz')]}")

DEFECTS = []
ABORT = [False]

# nearest-only searches: clean 200 face on an empty-but-existing collection
SEARCHES = [
    {"query": [1.0, 0.0, 0.0, 0.0], "limit": 3},
    {"query": [0.0, 1.0, 0.0, 0.0], "limit": 2},
]


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
    print(f"[liveness {tag}] healthz probe required")
    _hs, _hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={_hs} raw={str(_hraw)[:120]}")
    return _hs == 200


def result_of(raw):
    try:
        return json.loads(raw).get("result")
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        return None


def batch_query(tag, coll):
    s, raw = safe_request("POST", "query_batch",
                          path_params={"collection_name": coll},
                          body={"searches": SEARCHES})
    print(f"[{tag} batch query] status={s} raw={str(raw)[:260]}")
    return s, raw


def handle_leg(tag, status, raw, expect):
    """expect in ('404', '200'): judge the leg against the pinned disposition."""
    if status == 0:
        if not liveness(tag):
            ABORT[0] = True
        return
    if 500 <= status <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) batch query returned {status} with "
                           f"service alive — Type3_RuntimeFailure — "
                           f"raw={str(raw)[:150]}")
        else:
            ABORT[0] = True
        return
    if expect == "404" and status != 404:
        DEFECTS.append(f"({tag}) batch query on missing collection returned "
                       f"{status} — the assertion pins 404 for a missing "
                       f"collection — Type4_StateLogicViolation "
                       f"(qdrant_behavioral_points_query_batch_001) — "
                       f"raw={str(raw)[:150]}")
        return
    if expect == "404":
        print(f"[{tag}] OK: 404 as pinned")
        return
    if expect == "200" and status != 200:
        DEFECTS.append(f"({tag}) batch query on existing collection returned "
                       f"{status} — assertion pins 200 with one result per "
                       f"search — Type4_StateLogicViolation — "
                       f"raw={str(raw)[:150]}")
        return
    res = result_of(raw)
    if not isinstance(res, list):
        DEFECTS.append(f"({tag}) 200 batch result is not an array — "
                       f"Type4_StateLogicViolation (response_shape: result "
                       f"array)")
        return
    if len(res) != len(SEARCHES):
        DEFECTS.append(f"({tag}) 200 batch returned {len(res)} result "
                       f"entries for {len(SEARCHES)} searches — one result "
                       f"per search required — Type4_StateLogicViolation")
        return
    for i, entry in enumerate(res):
        if not isinstance(entry, dict) or not isinstance(entry.get("points"),
                                                         list):
            DEFECTS.append(f"({tag}) result[{i}] violates response_shape "
                           f"(object with points array): {str(entry)[:100]} "
                           f"— Type4_StateLogicViolation")
    print(f"[{tag}] OK: 200 with {len(res)} per-search entries")


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spqb1_" + TS + "_"
    C = PFX + "col"
    MISSING = PFX + "never_created"

    try:
        # (neg1) never-created collection -> pinned 404
        s, raw = batch_query("neg1-never-created", MISSING)
        handle_leg("neg1", s, raw, "404")

        # (pos) create -> identical body must flip to 200 + per-search results
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        s, raw = batch_query("pos-created", C)
        handle_leg("pos", s, raw, "200")

        # (neg2) drop -> identical body must return 404 again
        s_d, raw_d = safe_request("DELETE", "drop_collection",
                                  path_params={"name": C})
        print(f"[drop] status={s_d} raw={str(raw_d)[:160]}")
        if s_d not in (200, 201):
            print(f"SETUP_ERROR: drop returned {s_d}")
            return "SCRIPT_ERROR"
        # corroboration only (invariant qdrant_inv_delete_gone_001): details 404
        s_desc, raw_desc = safe_request("GET", "describe_collection",
                                        path_params={"name": C})
        print(f"[corroborate describe] status={s_desc} "
              f"raw={str(raw_desc)[:120]}")
        s, raw = batch_query("neg2-post-delete", C)
        handle_leg("neg2", s, raw, "404")

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        if ABORT[0]:
            print("ABORT: environment/transport unavailable mid-run")
            return "SCRIPT_ERROR"
        return "NO_DEFECT"
    finally:
        for _c in (C,):
            try:
                rt.drop_collection(_c)
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
