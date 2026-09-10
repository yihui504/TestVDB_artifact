#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_discover_positive_001
# strategy: strategy1 boundary positive-pairing + response-shape oracle
#           (the 200 [ScoredPoint] leg of the endpoint promise; G4 positive
#           control with boundary closure limit=1 and a dense-channel
#           attribution guard)
# endpoint: points+discover
# constraint_ids: qdrant_behavioral_points_discover_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/explore/discover-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism) — the promise's positive leg
#            is trusted by default; this script pins it with exact shape
#            checks against response_shape (result array; result[].id any;
#            result[].score number) so every later negative face rests on a
#            proven-live positive face
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 positive x qdrant_behavioral_points_discover_001 — the
  "valid discover returns HTTP 200 with scored points" leg is exercised on an
  own sparse+dense seeded collection (9 points, 3 red / 6 blue; sparse vector
  "text" over indices 1..3 = red cluster / 4..6 = blue cluster, per contract
  data_types "Sparse vector {indices: [uint], values: [float]}, distance
  always Dot"; named dense vector "dense" size 4 Cosine):
    G  guard: sparse target + context pair, using="text", limit=3
       -> 200, result ARRAY, 1 <= len <= 3, each element a ScoredPoint
       (id present, score numeric) — the promise's positive face.
    P1 target-only (sparse)         -> 200, result array, len >= 1
    P2 context-only (point-id pair) -> 200, result array, len >= 1
    D  dense control (using="dense", dense-array target) -> 200, result array
       — attribution guard: proves the endpoint is live on the dense channel,
       so a sparse-face failure cannot be blamed on the endpoint in general.
    B1 limit=1 (min legal value, boundary closure) -> 200, EXACTLY 1 result.
  [chunk_points+discover coverage: strategy1 positive/shape x
  qdrant_behavioral_points_discover_001 (this script; context/pairs type
  confusion in boundary_points_discover_context_type_002, 404 leg in
  boundary_points_discover_404_003, limit matrix in
  boundary_points_discover_limit_004, target/context presence matrix in
  boundary_points_discover_presence_005, sparse-target shape in
  boundary_points_discover_sparse_target_006, filter family mirror in
  boundary_points_discover_filter_type_007, malformed stream in
  boundary_points_discover_malformed_008)]
Oracle: G/P1/P2/D/B1 -> 200 with result a JSON array (len <= limit; B1
  exactly 1; P1/P2/D at least 1) and every element carrying an id and a
  numeric score (response_shape: result[] object / result[].id any /
  result[].score number); 200 with result not an array or a non-numeric
  score = shape violation (Type4_StateLogicViolation); 4xx on a valid face
  = promise violation (valid discover rejected — Type1 convention per
  session); 5xx with /healthz alive = Type3_RuntimeFailure; transport
  failure -> /healthz liveness re-check then SCRIPT_ERROR
  (constraint qdrant_behavioral_points_discover_001).
Constraint: qdrant_behavioral_points_discover_001 (bare id) — "returns 200
  [ScoredPoint]; 400 on invalid context/pairs; 404 for a missing collection"
  (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+discover       -> POST /collections/{collection_name}/points/discover
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
SPARSE_NAME = "text"
DENSE_NAME = "dense"
GUARD_TARGET = {"indices": [1, 2, 3], "values": [1.0, 1.0, 1.0]}
GUARD_CONTEXT = [{"positive": 1, "negative": 4}]


def safe_request(method, endpoint, json=None, timeout=60, params=None):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text); transport failure -> (-1, err, err).
    Query params (wait/ordering/timeout) via params= — never stuffed into the body.
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


def transport_dead(where):
    """Transport-branch liveness re-check (lightweight healthz face only)."""
    alive, hs, hraw = healthz_alive()
    print(f"transport failure on {where} (healthz status={hs}: {hraw})")
    print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
    return False


def sparse_vec(i):
    """Sparse vector per cluster: red over indices 1..3, blue over 4..6."""
    if i <= RED_N:
        return {"indices": [1, 2, 3], "values": [round(0.9 + 0.02 * i, 3), 0.8, 0.7]}
    return {"indices": [4, 5, 6], "values": [round(0.9 - 0.01 * i, 3), 0.85, 0.6]}


def dense_vec(i):
    """Dense vector per cluster (Cosine; absolute scores are never asserted)."""
    base = 0.1 if i <= RED_N else 0.9
    return [round(base + 0.001 * i, 4)] * DIM


def setup(coll):
    """Own collection: named dense vector + named sparse vector + 9 points."""
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {DENSE_NAME: {"size": DIM, "distance": "Cosine"}},
                                   "sparse_vectors": {SPARSE_NAME: {}}}, timeout=60)
    if s not in (200, 201):
        return False, raw
    pts = []
    for i in range(1, N_SEED + 1):
        pts.append({"id": i,
                    "vector": {DENSE_NAME: dense_vec(i), SPARSE_NAME: sparse_vec(i)},
                    "payload": {"grp": "red" if i <= RED_N else "blue"}})
    s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                             json={"points": pts}, params={"wait": "true"}, timeout=120)
    if s not in (200, 201):
        return False, raw
    return True, ""


def discover(coll, body):
    """points+discover face."""
    return safe_request("POST", f"/collections/{coll}/points/discover",
                        json=body, timeout=60)


def result_list(body):
    """Envelope extraction per response_shape: result is an array."""
    r = body.get("result") if isinstance(body, dict) else None
    return r if isinstance(r, list) else None


def scored_point_ok(p):
    """ScoredPoint shape per response_shape: object with id (any) + score (number)."""
    if not isinstance(p, dict) or "id" not in p:
        return False
    sc = p.get("score")
    return isinstance(sc, (int, float)) and not isinstance(sc, bool)


def judge_positive(label, s, raw, body, min_len, max_len):
    """Shared adjudication for a positive face (declare expectation first)."""
    if s == -1:
        return transport_dead(label)
    print(f"\n{label} -> status={s}")
    print(f"raw: {raw[:400]}")
    if 500 <= s <= 599:
        alive, _, _ = healthz_alive()
        if alive:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {label}: valid "
                  f"discover returned {s}: {raw[:300]}")
        else:
            print(f"VERDICT: SCRIPT_ERROR — {label} 5xx and healthz down")
        return False
    if not (200 <= s <= 299):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: valid "
              f"discover rejected with {s} (promise: HTTP 200 with scored "
              f"points): {raw[:300]}")
        return False
    res = result_list(body)
    if res is None:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — {label}: 200 "
              f"but result is not a JSON array (response_shape: result array): {raw[:300]}")
        return False
    if not (min_len <= len(res) <= max_len):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — {label}: 200 "
              f"but result length {len(res)} outside [{min_len}, {max_len}] "
              f"(limit bound / seeded-substrate bound): {raw[:300]}")
        return False
    bad = [p for p in res if not scored_point_ok(p)]
    if bad:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — {label}: 200 "
              f"but {len(bad)} result element(s) lack id/numeric-score "
              f"(response_shape result[].id/result[].score): {raw[:300]}")
        return False
    print(f"{label}: 200, result array len={len(res)}, ScoredPoint shape ok")
    return True


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpdw1" + tag

    ok, raw = setup(coll)
    if not ok:
        print(f"setup failed: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        base = {"using": SPARSE_NAME}

        # ---- G: guard — sparse target + context pair -> 200, 1..3 scored points ----
        gbody = dict(base, target=GUARD_TARGET, context=GUARD_CONTEXT, limit=3)
        s, body, raw = discover(coll, gbody)
        if not judge_positive("G guard sparse target+context", s, raw, body, 1, 3):
            return

        # ---- P1: target-only (sparse) -> 200, >= 1 ----
        p1 = dict(base, target=GUARD_TARGET, limit=3)
        s, body, raw = discover(coll, p1)
        if not judge_positive("P1 target-only sparse", s, raw, body, 1, 3):
            return

        # ---- P2: context-only (point-id pair) -> 200, >= 1 ----
        p2 = dict(base, context=GUARD_CONTEXT, limit=3)
        s, body, raw = discover(coll, p2)
        if not judge_positive("P2 context-only pair", s, raw, body, 1, 3):
            return

        # ---- D: dense control -> 200, >= 1 (attribution guard) ----
        dbody = {"using": DENSE_NAME, "target": dense_vec(1), "limit": 3}
        s, body, raw = discover(coll, dbody)
        if not judge_positive("D dense control", s, raw, body, 1, 3):
            return

        # ---- B1: limit=1 boundary closure -> 200, EXACTLY 1 ----
        b1 = dict(base, target=GUARD_TARGET, limit=1)
        s, body, raw = discover(coll, b1)
        if not judge_positive("B1 limit=1 closure", s, raw, body, 1, 1):
            return

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
