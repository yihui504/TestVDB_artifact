#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_discover_limit_004
# strategy: strategy1 boundary-value matrix on the required integer limit
#           (min closure / 0 / negative / null / missing / type-confused
#           string) + one strategy6 resource-extreme face (INT_MAX) — the
#           limit dimension of the 200/400 legs of the endpoint promise
# endpoint: points+discover
# constraint_ids: qdrant_behavioral_points_discover_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/explore/discover-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — limit is declared required
#            integer; optimism assumes 0/-1/null/missing/string are coerced
#            or rejected; each face measures the actual disposition) +
#            BS-01 (limit as JSON string — type coercion trust)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 limit-boundary x qdrant_behavioral_points_discover_001 —
  the required integer parameter limit (contract parameter spec: required,
   type integer) is swept across its boundary matrix on a live sparse seeded
  collection (valid sparse target + context kept constant so limit is the
  only variable):
    G  limit=3 (in-bounds control)        -> 200, result array 1..3
    B1 limit=1 (min legal value, closure) -> 200, EXACTLY 1 result
    L1 limit=0    -> 400/422 clean (a zero result budget is not a valid
       discovery); 2xx = Type1_IllegalSuccess
    L2 limit=-1   -> 400/422 clean; 2xx = Type1_IllegalSuccess
    L3 limit=null -> 400/422 clean; 2xx = Type1_IllegalSuccess
    L4 limit omitted (required parameter) -> 400/422 clean; 2xx =
       Type1_IllegalSuccess (discovery ran on an undeclared default)
    L5 limit="3" (JSON string, BS-01)     -> 400/422 clean; 2xx =
       Type1_IllegalSuccess (string coerced to int)
    X1 limit=2147483647 (INT_MAX, strategy6 resource face) -> 200 with
       result len <= 9 (seeded substrate) OR 400/422 explicit rejection —
       both legal; 5xx / crash signals = Type3_RuntimeFailure.
  [chunk_points+discover coverage: strategy1 limit matrix + strategy6 extreme
  x qdrant_behavioral_points_discover_001 (this script; positive/shape in
  boundary_points_discover_positive_001, context type-confusion in
  boundary_points_discover_context_type_002, 404 leg in
  boundary_points_discover_404_003, presence matrix in
  boundary_points_discover_presence_005, sparse-target shape in
  boundary_points_discover_sparse_target_006, filter family mirror in
  boundary_points_discover_filter_type_007, malformed stream in
  boundary_points_discover_malformed_008)]
Oracle: G -> 200 result 1..3; B1 -> 200 EXACTLY 1 (other 200 length =
  Type4_StateLogicViolation); L1..L5 -> 400/422 clean rejection (any 2xx =
  Type1_IllegalSuccess: illegal/missing/mistyped limit accepted); X1 -> 200
  with len <= 9 or 400/422 (both NO_DEFECT; 5xx with /healthz alive =
  Type3_RuntimeFailure); 4xx on G/B1 = valid discover rejected (Type1
  convention per session); transport failure -> /healthz liveness re-check
  then SCRIPT_ERROR (constraint qdrant_behavioral_points_discover_001).
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
INT_MAX = 2147483647

# (label, body-builder over the constant valid part, expectation kind)
# kind: "pos:minlen:maxlen" for positive faces, "rej" for 400/422 faces,
#       "res" for the strategy6 resource face
FACES = [
    ("G limit=3 control", lambda b: dict(b, limit=3), ("pos", 1, 3)),
    ("B1 limit=1 min closure", lambda b: dict(b, limit=1), ("pos", 1, 1)),
    ("L1 limit=0", lambda b: dict(b, limit=0), ("rej",)),
    ("L2 limit=-1", lambda b: dict(b, limit=-1), ("rej",)),
    ("L3 limit=null", lambda b: dict(b, limit=None), ("rej",)),
    ("L4 limit omitted", lambda b: dict(b), ("rej",)),
    ("L5 limit as STRING '3'", lambda b: dict(b, limit="3"), ("rej",)),
    ("X1 limit=INT_MAX resource", lambda b: dict(b, limit=INT_MAX), ("res",)),
]


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


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpdw4" + tag

    ok, raw = setup(coll)
    if not ok:
        print(f"setup failed: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        base = {"using": SPARSE_NAME, "target": GUARD_TARGET, "context": GUARD_CONTEXT}
        for label, build, expect in FACES:
            body_ = build(base)
            s, body, raw = discover(coll, body_)
            print(f"\n{label} -> status={s}")
            print(f"raw: {raw[:400]}")
            if s == -1:
                transport_dead(label)
                return
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    kind = "Type3_RuntimeFailure"
                    print(f"VERDICT: DEFECT_FOUND ({kind}) — {label}: discover "
                          f"returned {s}: {raw[:300]}")
                else:
                    print(f"VERDICT: SCRIPT_ERROR — {label} 5xx and healthz down")
                return

            if expect[0] == "pos":
                _, lo, hi = expect
                if not (200 <= s <= 299):
                    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: "
                          f"valid discover rejected with {s} (promise: HTTP 200): "
                          f"{raw[:300]}")
                    return
                res = body.get("result") if isinstance(body, dict) else None
                if not isinstance(res, list) or not (lo <= len(res) <= hi):
                    got = len(res) if isinstance(res, list) else "non-array"
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                          f"{label}: 200 but result length {got} outside "
                          f"[{lo}, {hi}] (limit bound): {raw[:300]}")
                    return
                print(f"{label}: 200, result len={len(res)} within [{lo}, {hi}]")

            elif expect[0] == "rej":
                if 200 <= s <= 299:
                    res = body.get("result") if isinstance(body, dict) else None
                    got = len(res) if isinstance(res, list) else "non-array"
                    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: "
                          f"illegal limit ACCEPTED with status {s} and result "
                          f"length {got} (expected 400/422 clean rejection): "
                          f"{raw[:300]}")
                    return
                if s in (400, 422):
                    low = raw.lower()
                    named = "limit" in low
                    note = ("diagnostics name the limit parameter"
                            if named else
                            "NOTE (strategy5): rejection text names no 'limit' "
                            "token — diagnostics gap recorded for the judge")
                    print(f"{label}: {s} clean rejection; {note}")
                else:
                    print(f"NOTE: {label} returned {s} (neither 2xx nor 400/422); "
                          f"recorded for the judge — unexpected rejection class")

            else:  # resource face
                if 200 <= s <= 299:
                    res = body.get("result") if isinstance(body, dict) else None
                    if not isinstance(res, list) or len(res) > N_SEED:
                        got = len(res) if isinstance(res, list) else "non-array"
                        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                              f"{label}: 200 but result {got} exceeds the seeded "
                              f"substrate ({N_SEED}): {raw[:300]}")
                        return
                    print(f"VERDICT-relevant: {label}: accepted, returned "
                          f"{len(res)} results (<= {N_SEED} seeded) — no crash, "
                          f"resource face clean")
                elif s in (400, 422):
                    print(f"{label}: {s} explicit rejection — legal resource outcome")
                else:
                    print(f"NOTE: {label} returned {s}; recorded for the judge")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
