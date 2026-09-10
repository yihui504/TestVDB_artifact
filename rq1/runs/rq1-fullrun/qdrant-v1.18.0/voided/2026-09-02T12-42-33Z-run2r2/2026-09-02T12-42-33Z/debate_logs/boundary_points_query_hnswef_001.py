#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_query_hnswef_001
# strategy: strategy1 boundary-value attack on SearchParams.hnsw_ef of the
#           universal query API (min-1 promise) + strategy2 type-confusion
#           cross-leg + strategy5 error-quality observation (R29: no verdict
#           weight on error naming)
# endpoint: points+query
# constraint_ids: qdrant_range_points_query_002
# source_url: https://qdrant.tech/documentation/search/search/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-04 (Boundary Default Optimism — hnsw_ef>=1 is trusted by
#            default; hnsw_ef=0/-1 accepted with 200 would silently corrupt
#            the ef knob and with it the recall contract of the search)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary x qdrant_range_points_query_002 — the contract
  asserts "SearchParams: hnsw_ef minimum 1" on POST /collections/{c}/
  points/query. Boundary matrix on a 6-point seeded collection (dim 4,
  Euclid; fixed nearest query):
    E1    params={"hnsw_ef": 1} (min legal   -> 200 with >= 1 point
          closure)
    E128  params={"hnsw_ef": 128} (legal     -> 200 with >= 1 point
          large value)
    E0    params={"hnsw_ef": 0} (min-1       -> 400/422 reject
          boundary)
    Eneg  params={"hnsw_ef": -1} (negative)  -> 400/422 reject
    Etype params={"hnsw_ef": "64"} (string,  -> 400/422 reject
          strategy2 cross-leg)
  Error-quality (strategy5) observation is PRINTED ONLY (does the 4xx name
  hnsw_ef) — per R29 standing lesson error-naming carries no verdict weight.
  [chunk_points+query coverage: strategy1+6 limit x range_points_query_001
  (limit_001); strategy1 offset x range_points_query_001 (offset_001);
  strategy1 hnsw_ef x range_points_query_002 (this script); strategy1
  acorn_scale x range_points_query_002 (acorn_001); strategy2 oneOf-domain
  negative x type_points_query_001 (variant_type_001); strategy2 oneOf-domain
  positive closure x type_points_query_001 (variant_matrix_001); strategy2
  invalid-query/filter + 404 x behavioral_points_query_001 (envelope_001);
  strategy7 malformed stream x behavioral_points_query_001 (malformed_001);
  strategy3 by-id vector characteristic mismatch x state_points_query_001
  (byid_dim_001); state by-id missing-point x state_points_query_001
  (byid_stale_001); strategy1 query-absent id-order x
  behavioral_points_query_004 (noid_order_001); strategy1 exact=true
  pagination stability x behavioral_points_query_003 (offset_exact_001);
  strategy6 huge-offset resource x behavioral_points_query_002
  (offset_huge_001)]
Oracle: E1/E128 -> 200 with a non-empty points array (4xx on a documented
  legal value = Type1_IllegalSuccess); E0/Eneg/Etype -> 400 or 422 (200 =
  Type1_IllegalSuccess: the min-1 promise is violated by accepting the
  request; 5xx with /healthz alive = Type3_RuntimeFailure; transport
  failure -> /healthz re-check then SCRIPT_ERROR) (constraint
  qdrant_range_points_query_002).
Constraint: qdrant_range_points_query_002 (bare id) — "SearchParams:
  hnsw_ef minimum 1; acorn_scale within [0.0, 1.0] (default 0.4)"
  (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+query        -> POST /collections/{collection_name}/points/query
  points+upsert       -> PUT  /collections/{collection_name}/points
  collections+create  -> PUT  /collections/{collection_name}
  collections+delete  -> DELETE /collections/{collection_name}
  healthz             -> GET  /healthz
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
N_SEED = 6
V = [0.5, 0.25, 0.125, 0.0625]


def safe_request(method, endpoint, json=None, timeout=60, params=None):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text); transport failure -> (-1, err, err).
    Query params (wait/consistency) via params= — never stuffed into the body.
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


def extract_points(body):
    """
    Locate the ScoredPoint array in the QueryResponse envelope.
    Contract response_shape: result (object) -> result.points (array).
    A legacy list-form result is tolerated and reported (shape oracles
    cross-checked against the published OpenAPI — standing lesson).
    """
    if not isinstance(body, dict):
        return None, "body-not-dict"
    result = body.get("result")
    if isinstance(result, dict):
        pts = result.get("points")
        return (pts if isinstance(pts, list) else None), "result.points"
    if isinstance(result, list):
        return result, "result-array-observed"
    return None, "result-missing"


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpqE1" + tag

    # Arrange: own collection, own data, own cleanup
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        pts = [{"id": i, "vector": [v * (1.0 + i / 100.0) for v in V]} for i in range(1, N_SEED + 1)]
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": pts}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return

        base_body = {"query": {"nearest": V}, "limit": 3}

        # ---- Positive legs: E1 (min closure) / E128 (legal large) ----
        for label, ef in (("E1 hnsw_ef=1", 1), ("E128 hnsw_ef=128", 128)):
            s, b, raw = safe_request("POST", f"/collections/{coll}/points/query",
                                     json=dict(base_body, params={"hnsw_ef": ef}), timeout=60)
            print(f"\nleg {label} -> status={s}")
            print(f"raw: {raw[:400]}")
            if s == -1:
                alive, _, _ = healthz_alive()
                print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion" if alive else
                      "VERDICT: SCRIPT_ERROR — transport failure and healthz down")
                return
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: valid "
                          f"hnsw_ef returned {s} with service alive: {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return
            pts_a, shape = extract_points(b)
            if s != 200 or pts_a is None:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{label}]: hnsw_ef={ef} "
                      f"is a documented legal value but the request failed with {s}: {raw[:300]}")
                return
            if len(pts_a) < 1:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [{label}]: "
                      f"{N_SEED} seeded points and limit=3 must yield >= 1 point, got 0: {raw[:300]}")
                return
            print(f"leg {label} OK: 200 with {len(pts_a)} points (envelope {shape})")

        # ---- Negative legs: E0 / Eneg / Etype -> must be rejected ----
        for label, ef in (("E0 hnsw_ef=0", 0), ("Eneg hnsw_ef=-1", -1),
                          ("Etype hnsw_ef='64'", "64")):
            s, b, raw = safe_request("POST", f"/collections/{coll}/points/query",
                                     json=dict(base_body, params={"hnsw_ef": ef}), timeout=60)
            print(f"\nleg {label} -> status={s}")
            print(f"raw: {raw[:400]}")
            if s == -1:
                alive, _, _ = healthz_alive()
                print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion" if alive else
                      "VERDICT: SCRIPT_ERROR — transport failure and healthz down")
                return
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: illegal "
                          f"hnsw_ef returned {s} (must be a clean 4xx) with service alive: {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return
            if s == 200:
                n = len(extract_points(b)[0] or [])
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{label}]: contract "
                      f"asserts hnsw_ef minimum 1, but the request was ACCEPTED with 200 "
                      f"({n} points returned): {raw[:300]}")
                return
            if s not in (400, 422):
                print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on leg [{label}]; no defect conclusion")
                return
            # strategy5 observation only (R29: error-naming has no verdict weight)
            named = "hnsw_ef" in raw.lower() or "ef" in raw.lower()
            print(f"leg {label} OK: rejected with {s} (error names the param: {named})")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
