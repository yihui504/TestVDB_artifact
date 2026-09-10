#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_query_batch_positive_001
# strategy: strategy1 boundary-value attack, positive side (G4 pairing) on
#           the batch core promise: one result per search, same order
# endpoint: points+query+batch
# constraint_ids: qdrant_behavioral_points_query_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/batch-query
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — clients trust that a batch of
#            N queries returns exactly N results in input order; a server
#            reordering, truncating, or dropping per-query results breaks
#            client result-attribution silently)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 positive core x
  qdrant_behavioral_points_query_batch_001 — the assertion promises "HTTP 200
  with one result per search in the same order". Positive legs on a seeded
  9-point collection (dim 4, Cosine; red ids 1-3 vector-aligned with axis-1,
  blue ids 4-9 aligned with axis-2; payload grp + rank=i):
    B1 3-entry batch with FILTER-DISJOINT entries:
       e1 nearest(blue-vec) + filter grp=red   -> only red ids possible
       e2 nearest(blue-vec) + filter grp=blue  -> only blue ids possible
       e3 order_by rank asc (no vector)        -> ids exactly [1,2,3]
       Attribution is contract-grounded via filter membership (documented
       Filter semantics) and order_by direction — NO invented score oracles
       (R39 lesson); if the server reordered result elements, e1/e2
       fingerprints swap and the order promise is caught.
    B2 single-entry batch (min meaningful batch size) -> outer len exactly 1.
  [chunk_points+query+batch coverage: strategy1 positive order/count core x
  behavioral_points_query_batch_001 (this script); assertion 404 leg x
  behavioral_points_query_batch_001 (404_002); strategy2 searches wrapper
  type x behavioral_points_query_batch_001 (searches_type_003); strategy2
  entry presence matrix x behavioral_points_query_batch_001 (presence_004);
  R33-family dual-key enum discard x behavioral_points_query_batch_001
  (dualkey_005); strategy1 per-entry limit x behavioral_points_query_batch_001
  + range_points_query_001 min-1 ground (limit_006); strategy1 per-entry
  offset x behavioral_points_query_batch_001 + range_points_query_001 min-0
  ground (offset_007); mixed-variant universal-queries promise x
  behavioral_points_query_batch_001 (mixed_008); strategy6 batch-size
  resource x behavioral_points_query_batch_001 (resource_009); strategy7
  malformed stream x behavioral_points_query_batch_001 (malformed_010)]
Oracle: B1 -> 200 with result array outer len EXACTLY 3 (N-in/N-out),
  result[i] an object carrying a points array (response_shape result[].points),
  result[0] ids subset of {1,2,3} len<=3, result[1] ids subset of {4..9}
  len<=3, result[2] ids exactly [1,2,3] (any violation = Type4
  _StateLogicViolation: count/order/attribution promise broken); 4xx on B1 or
  B2 = Type1_IllegalSuccess convention (valid documented batch rejected;
  promise says HTTP 200); 5xx with /healthz alive = Type3_RuntimeFailure;
  transport failure -> /healthz liveness re-check then SCRIPT_ERROR
  (constraint qdrant_behavioral_points_query_batch_001).
Constraint: qdrant_behavioral_points_query_batch_001 (bare id) — "executes
  multiple queries in one call; returns 200 with a list of per-query results;
  404 for a missing collection" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+query+batch    -> POST /collections/{collection_name}/points/query/batch
  collections+create    -> PUT  /collections/{collection_name}
  collections+delete    -> DELETE /collections/{collection_name}
  points+upsert         -> PUT  /collections/{collection_name}/points
  healthz               -> GET  /healthz
  (wait is a query parameter on the upsert face — passed via params=)
"""

import json
import os
import sys
import uuid
from pathlib import Path

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# --- X1 bootstrap: three-layer fallback (env -> upward walk -> contract target) ---
BASE_URL = os.environ.get("TESTVDB_DB_URL")
TARGET = os.environ.get("TESTVDB_TARGET", "")
if not TARGET:
    _root = Path(__file__).resolve()
    for _p in (_root, *list(_root.parents)):
        _f = _p / "structured_contract.json"
        if _f.exists():
            try:
                _c = json.loads(_f.read_text(encoding="utf-8"))
                TARGET = _c.get("target", "") or TARGET
            except Exception:
                pass
            break
if not BASE_URL or TARGET != "qdrant":
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL/TESTVDB_TARGET missing (bootstrap fallback failed)")
    sys.exit(2)

DIM = 4
N_SEED = 9
RED_N = 3
RED_IDS = set(range(1, RED_N + 1))
BLUE_IDS = set(range(RED_N + 1, N_SEED + 1))
RED_VEC = [1.0, 0.0, 0.0, 0.0]
BLUE_VEC = [0.0, 1.0, 0.0, 0.0]


def safe_request(method, endpoint, json=None, timeout=60, params=None):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text); transport failure -> (-1, err, err).
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(
            method=method, url=url, json=json, headers=headers,
            timeout=timeout, params=params,
        )
        status_code = response.status_code
        raw_text = response.text
        try:
            body = response.json()
        except Exception:
            body = raw_text
        return status_code, body, raw_text
    except Exception as e:
        return -1, str(e), str(e)


def healthz_alive():
    """Inline liveness probe on the lightweight healthz face."""
    hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
    return hs == 200, hs, str(hraw)[:200]


def point_vec(i):
    # red ids: aligned with axis-1; blue ids: aligned with axis-2 — cosine-
    # disjoint directions so nearest() attribution is deterministic
    if i <= RED_N:
        return [1.0, round(0.001 * i, 4), 0.0, 0.0]
    return [round(0.001 * i, 4), 1.0, 0.0, 0.0]


def setup(coll):
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Cosine"}},
                             timeout=60)
    if s not in (200, 201):
        return False, raw
    pts = [{"id": i, "vector": point_vec(i),
            "payload": {"grp": "red" if i <= RED_N else "blue", "rank": i}}
           for i in range(1, N_SEED + 1)]
    s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                             json={"points": pts}, params={"wait": "true"},
                             timeout=120)
    if s not in (200, 201):
        return False, raw
    return True, ""


def query_batch(coll, body, timeout=60):
    return safe_request("POST", f"/collections/{coll}/points/query/batch",
                        json=body, timeout=timeout)


def ids_of_entry(res_elem):
    """ids of one per-query result element; None if the element is not an
    object carrying a points array (response_shape: result[].points)."""
    if not isinstance(res_elem, dict) or not isinstance(res_elem.get("points"), list):
        return None
    out = []
    for p in res_elem["points"]:
        if not isinstance(p, dict) or "id" not in p:
            return None
        out.append(p.get("id"))
    return out


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpqb1" + tag

    ok, raw = setup(coll)
    if not ok:
        print(f"setup failed: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        # --- B1: 3-entry filter-disjoint batch (order + count core) ---
        body_b1 = {"searches": [
            {"query": {"nearest": list(BLUE_VEC)}, "filter": {
                "must": [{"key": "grp", "match": {"value": "red"}}]}, "limit": 3},
            {"query": {"nearest": list(BLUE_VEC)}, "filter": {
                "must": [{"key": "grp", "match": {"value": "blue"}}]}, "limit": 3},
            {"query": {"order_by": {"key": "rank", "direction": "asc"}},
             "limit": 3},
        ]}
        s, body, raw = query_batch(coll, body_b1)
        print(f"B1 3-entry batch -> status={s}")
        print(f"raw: {raw[:500]}")
        if s == -1:
            alive, hs, hraw = healthz_alive()
            print(f"transport failure on B1 (healthz status={hs}: {hraw})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — B1: valid "
                      f"batch returned {s}: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — B1 5xx and healthz down")
            return
        if not (200 <= s <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — B1: valid "
                  f"documented batch rejected with {s} (promise: HTTP 200 "
                  f"one result per search): {raw[:300]}")
            return
        res = body.get("result") if isinstance(body, dict) else None
        if not isinstance(res, list) or len(res) != 3:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — B1: 200 "
                  f"but outer result len={len(res) if isinstance(res, list) else 'non-list'} "
                  f"(promise: one result per search, expected 3): {raw[:300]}")
            return
        ids0, ids1, ids2 = (ids_of_entry(res[0]), ids_of_entry(res[1]),
                            ids_of_entry(res[2]))
        if ids0 is None or ids1 is None or ids2 is None:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — B1: a "
                  f"result element is not an object carrying a points array "
                  f"(response_shape result[].points): {raw[:300]}")
            return
        s0, s1, s2 = set(ids0), set(ids1), set(ids2)
        if not (len(ids0) <= 3 and s0 <= RED_IDS):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — B1 "
                  f"result[0] attribution broken: expected subset of red ids "
                  f"(filter grp=red), got {ids0}: {raw[:300]}")
            return
        if not (len(ids1) <= 3 and s1 <= BLUE_IDS):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — B1 "
                  f"result[1] attribution broken: expected subset of blue ids "
                  f"(filter grp=blue), got {ids1} — count/order promise or "
                  f"filter semantics broken on this face: {raw[:300]}")
            return
        if ids2 != [1, 2, 3]:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — B1 "
                  f"result[2] attribution broken: expected order_by rank asc "
                  f"== [1, 2, 3], got {ids2}: {raw[:300]}")
            return
        print(f"B1 upheld: outer=3, result[0]={ids0} (red), "
              f"result[1]={ids1} (blue), result[2]={ids2} (rank asc)")

        # --- B2: single-entry batch (min meaningful batch size) ---
        body_b2 = {"searches": [body_b1["searches"][1]]}
        s, body, raw = query_batch(coll, body_b2)
        print(f"\nB2 single-entry batch -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            alive, hs, hraw = healthz_alive()
            print(f"transport failure on B2 (healthz status={hs}: {hraw})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — B2: "
                      f"returned {s}: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — B2 5xx and healthz down")
            return
        if not (200 <= s <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — B2: valid "
                  f"single-entry batch rejected with {s} (promise: HTTP 200): "
                  f"{raw[:300]}")
            return
        res = body.get("result") if isinstance(body, dict) else None
        if not isinstance(res, list) or len(res) != 1:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — B2: 200 "
                  f"but outer result len={len(res) if isinstance(res, list) else 'non-list'} "
                  f"(expected exactly 1): {raw[:300]}")
            return
        ids0 = ids_of_entry(res[0])
        if ids0 is None or not (set(ids0) <= BLUE_IDS and len(ids0) <= 3):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — B2 "
                  f"result[0] attribution broken (filter grp=blue, limit 3), "
                  f"got {ids0}: {raw[:300]}")
            return
        print(f"B2 upheld: outer=1, result[0]={ids0} (blue)")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
