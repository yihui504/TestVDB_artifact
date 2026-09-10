#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_discover_batch_positive_001
# strategy: strategy1 positive control with a batch-alignment state oracle
#           (envelope result is array-of-arrays: exactly one discover-result
#           array per query, in order; per-query expectations arithmetic-
#           derived from the seeded substrate with id-membership analysis)
# endpoint: points+discover+batch
# constraint_ids: qdrant_behavioral_points_discover_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/explore/discover-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — the batch face's promise is
#            not just "200 [ScoredPoint]" but N-in/N-out alignment; a batch
#            implementation that zips, drops, or reorders per-query results
#            still returns 200 and passes any bare status check)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 positive + alignment oracle x
  qdrant_behavioral_points_discover_batch_001 — the 200 leg of the batch
  promise is exercised by a 3-query batch whose per-query expectations are
  derived arithmetically from the seeded substrate (R33 discipline) and whose
  per-query result pools are DISJOINT by construction, so any mis-zip,
  drop, or reorder of the batch alignment is detectable from membership
  alone (R36 batch-variant lesson: one discover-result array per query, in
  order; envelope result is array-of-arrays per contract response_shape
  "result[]": "array"):
    Q0 context-only [{"positive":1,"negative":4}] + filter grp=red,
       limit=2 -> inner array EXACTLY 2, ids subset of {1,2,3}
    Q1 target=1 (point id) + filter grp=blue, limit=3 -> inner EXACTLY 3,
       ids subset of {4..9}
    Q2 target=[0.1]*4 (dense vector), limit=1 -> inner EXACTLY 1, any id
  Substrate: 9 points, ids 1..9, red=1..3 / blue=4..9, unnamed dense dim 4
  (below default indexing_threshold full-scan plain index, so counts are
  exact, not approximate).
  [chunk_points+discover+batch coverage: positive+batch-alignment x
  qdrant_behavioral_points_discover_batch_001 (this script; searches-wrapper
  type-confusion in boundary_points_discover_batch_searches_type_002,
  context/pairs type-confusion+atomicity in
  boundary_points_discover_batch_context_type_003, 404 leg in
  boundary_points_discover_batch_404_004, limit matrix in
  boundary_points_discover_batch_limit_005, target/context presence in
  boundary_points_discover_batch_presence_006, sparse-target shape in
  boundary_points_discover_batch_sparse_target_007, malformed stream in
  boundary_points_discover_batch_malformed_008, resource/batch-size in
  boundary_points_discover_batch_resource_009)]
Oracle: 200 with result array-of-arrays, outer len EXACTLY 3 (N-in/N-out);
  inner lengths EXACTLY [2, 3, 1] (arithmetic: 3 red candidates cap 2, 6
  blue cap 3, 9 any cap 1); Q0 ids subset {1,2,3} and Q1 ids subset {4..9}
  (membership misroute = Type4_StateLogicViolation); each element a dict
  with an id; duplicate ids within one inner array = Type4; non-2xx = valid
  batch rejected (Type1 convention per session); 5xx with /healthz alive =
  Type3_RuntimeFailure; transport failure -> /healthz liveness re-check then
  SCRIPT_ERROR (constraint qdrant_behavioral_points_discover_batch_001).
Constraint: qdrant_behavioral_points_discover_batch_001 (bare id) — "returns
  200 [ScoredPoint]; 400 on invalid context/pairs; 404 for a missing
  collection" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+discover+batch -> POST /collections/{collection_name}/points/discover/batch
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


def safe_request(method, endpoint, json=None, timeout=60, params=None):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text); transport failure -> (-1, err, err).
    Query params (wait/ordering) via params= — never stuffed into the body.
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


def dense_vec(i):
    """Dense vector per cluster (Cosine; absolute scores are never asserted)."""
    base = 0.1 if i <= RED_N else 0.9
    return [round(base + 0.001 * i, 4)] * DIM


def setup(coll):
    """Own collection: unnamed dense vector + 9 red/blue points."""
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Cosine"}},
                             timeout=60)
    if s not in (200, 201):
        return False, raw
    pts = []
    for i in range(1, N_SEED + 1):
        pts.append({"id": i, "vector": dense_vec(i),
                    "payload": {"grp": "red" if i <= RED_N else "blue"}})
    s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                             json={"points": pts}, params={"wait": "true"},
                             timeout=120)
    if s not in (200, 201):
        return False, raw
    return True, ""


def discover_batch(coll, body):
    """points+discover+batch face."""
    return safe_request("POST", f"/collections/{coll}/points/discover/batch",
                        json=body, timeout=90)


def inner_ids(arr):
    """Extract ids from one inner result array; None if shape is wrong."""
    if not isinstance(arr, list):
        return None
    ids = []
    for p in arr:
        if not isinstance(p, dict) or "id" not in p:
            return None
        ids.append(p.get("id"))
    return ids


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpdwb1" + tag

    ok, raw = setup(coll)
    if not ok:
        print(f"setup failed: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        # (label, query, expected inner len, allowed id pool or None)
        plan = [
            ("Q0 context+filter red, limit=2",
             {"context": [{"positive": 1, "negative": 4}],
              "filter": {"must": [{"key": "grp", "match": {"value": "red"}}]},
              "limit": 2}, 2, RED_IDS),
            ("Q1 target=1+filter blue, limit=3",
             {"target": 1,
              "filter": {"must": [{"key": "grp", "match": {"value": "blue"}}]},
              "limit": 3}, 3, BLUE_IDS),
            ("Q2 target dense vector, limit=1",
             {"target": [0.1] * DIM, "limit": 1}, 1, None),
        ]
        queries = [q for _, q, _, _ in plan]
        s, body, raw = discover_batch(coll, {"searches": queries})
        print(f"discover/batch -> status={s}")
        print(f"raw: {raw[:600]}")
        if s == -1:
            alive, hs, hraw = healthz_alive()
            print(f"transport failure (healthz status={hs}: {hraw})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — valid batch "
                      f"returned {s}: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
            return
        if not (200 <= s <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — valid 3-query "
                  f"batch rejected with {s} (promise: HTTP 200): {raw[:300]}")
            return

        res = body.get("result") if isinstance(body, dict) else None
        if not isinstance(res, list):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — 200 but "
                  f"result is not an array (response_shape: result array): "
                  f"{raw[:300]}")
            return
        if len(res) != len(plan):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — batch "
                  f"alignment broken: {len(plan)} queries in, {len(res)} result "
                  f"arrays out (envelope result[]: array, one per query in "
                  f"order): {raw[:300]}")
            return

        for idx, (label, _, want_len, pool) in enumerate(plan):
            ids = inner_ids(res[idx])
            if ids is None:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — {label}: "
                      f"inner result[{idx}] is not an array of id-bearing objects: "
                      f"{str(res[idx])[:200]}")
                return
            if len(ids) != want_len:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — {label}: "
                      f"inner len {len(ids)} != arithmetic expectation {want_len} "
                      f"(substrate: 3 red / 6 blue / 9 any; plain-index full scan "
                      f"below default indexing_threshold): {raw[:300]}")
                return
            if len(set(ids)) != len(ids):
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — {label}: "
                      f"duplicate ids within one query's result: {ids}")
                return
            if pool is not None and not set(ids).issubset(pool):
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — {label}: "
                      f"ids {ids} outside the query's filter pool {sorted(pool)} "
                      f"(batch result misroute/mis-zip): {raw[:300]}")
                return
            print(f"{label}: inner len={len(ids)} ids={ids} (aligned)")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
