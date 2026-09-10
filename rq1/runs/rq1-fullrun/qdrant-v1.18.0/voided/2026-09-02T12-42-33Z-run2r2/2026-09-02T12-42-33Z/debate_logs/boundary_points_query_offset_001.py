#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_query_offset_001
# strategy: strategy1 boundary-value attack on the offset parameter of the
#           universal query API (min-0 promise + next_page_offset arithmetic
#           + empty-page semantics at/beyond the collection size)
# endpoint: points+query
# constraint_ids: qdrant_range_points_query_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — offset>=0 trusted by default;
#            offset=12 == count and offset=13 > count are the exact seam
#            where an off-by-one would resurrect points or 4xx a legal page)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary x qdrant_range_points_query_001 — the contract
  asserts "offset minimum 0 (default 0)" on POST /collections/{c}/points/
  query. Boundary matrix on a 12-point seeded collection (dim 4, Euclid),
  fixed nearest query + limit=5 (12 = 5+5+2 pages: page math is
  arithmetic-derived, id-collision-free by construction):
    Of0      offset=0 (min legal closure)  -> 200, EXACTLY 5 points,
                                              next_page_offset == 5
    Of5      offset=5 (mid boundary)       -> 200, EXACTLY 5 points,
                                              next_page_offset == 10
    Ofeq     offset=12 (== N_SEED)         -> 200, 0 points, NO
                                              next_page_offset (page past
                                              the end is legal and empty)
    Ofbeyond offset=13 (> N_SEED)          -> 200, 0 points, NO
                                              next_page_offset
    Ofneg    offset=-1 (min-1 boundary)    -> 400/422 reject
    Oftype   offset="0" (string,           -> 400/422 reject
             strategy2 cross-leg)
  NOTE: page-content disjointness across offsets is NOT asserted here —
  HNSW offset pagination may repeat points by-design (threat model /
  behavioral_points_query_003); only counts and next_page_offset
  arithmetic are contract-derivable on this face.
  [chunk_points+query coverage: strategy1+6 limit x range_points_query_001
  (limit_001); strategy1 offset x range_points_query_001 (this script);
  strategy1 hnsw_ef x range_points_query_002 (hnswef_001); strategy1
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
Oracle: Of0 -> 200 with exactly 5 points and next_page_offset == 5; Of5 ->
  200 with exactly 5 points and next_page_offset == 10; Ofeq/Ofbeyond ->
  200 with 0 points and next_page_offset absent (non-empty page or 4xx on
  a legal offset = Type1_IllegalSuccess; wrong count/next_page_offset
  arithmetic = Type4_StateLogicViolation); Ofneg/Oftype -> 400 or 422
  (200 = Type1_IllegalSuccess: min-0 promise violated by accepting -1 or a
  string); 5xx with /healthz alive = Type3_RuntimeFailure; transport
  failure -> /healthz re-check then SCRIPT_ERROR (constraint
  qdrant_range_points_query_001).
Constraint: qdrant_range_points_query_001 (bare id) — "limit minimum 1
  (default 10); offset minimum 0 (default 0)" (evidence_tier: explicit;
  level: endpoint)

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
N_SEED = 12
PAGE = 5
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


def extract_next_offset(body):
    """next_page_offset lives in the result object (contract: next_page_offset?)."""
    result = body.get("result") if isinstance(body, dict) else None
    if isinstance(result, dict):
        return result.get("next_page_offset")
    if isinstance(result, list):
        return body.get("next_page_offset")
    return None


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpqO1" + tag

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

        # ---- Positive boundary legs with arithmetic-derived oracles ----
        for label, off, exp_n, exp_npo in (
            ("Of0 offset=0", 0, PAGE, 5),
            ("Of5 offset=5", 5, PAGE, 10),
            ("Ofeq offset=12==N", N_SEED, 0, None),
            ("Ofbeyond offset=13>N", N_SEED + 1, 0, None),
        ):
            s, b, raw = safe_request("POST", f"/collections/{coll}/points/query",
                                     json={"query": {"nearest": V}, "limit": PAGE,
                                           "offset": off}, timeout=60)
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
                          f"offset={off} returned {s} with service alive: {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return
            pts_a, shape = extract_points(b)
            if s in (400, 404, 422):
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{label}]: offset={off} "
                      f"is inside the documented domain (min 0, {N_SEED} points stored) but the "
                      f"request was rejected with {s}: {raw[:300]}")
                return
            if s != 200 or pts_a is None:
                print(f"VERDICT: SCRIPT_ERROR — unexpected status/envelope {s} ({shape}); no defect conclusion")
                return
            if len(pts_a) != exp_n:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [{label}]: "
                      f"offset={off} + limit={PAGE} over {N_SEED} points must yield exactly "
                      f"{exp_n} points (min(PAGE, max(0, {N_SEED}-{off}))), got {len(pts_a)}: "
                      f"{raw[:300]}")
                return
            npo = extract_next_offset(b)
            if npo != exp_npo:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [{label}]: "
                      f"next_page_offset must be {exp_npo!r} ({len(pts_a)} shown from offset "
                      f"{off}), got {npo!r}: {raw[:300]}")
                return
            print(f"leg {label} OK: {exp_n} points, next_page_offset={exp_npo} (envelope {shape})")

        # ---- Negative legs: Ofneg / Oftype -> must be rejected ----
        for label, off in (("Ofneg offset=-1", -1), ("Oftype offset='0'", "0")):
            s, b, raw = safe_request("POST", f"/collections/{coll}/points/query",
                                     json={"query": {"nearest": V}, "limit": PAGE,
                                           "offset": off}, timeout=60)
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
                          f"offset returned {s} (must be a clean 4xx) with service alive: {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return
            if s == 200:
                n = len(extract_points(b)[0] or [])
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{label}]: contract "
                      f"asserts offset minimum 0 (unsigned), but the request was ACCEPTED with "
                      f"200 ({n} points returned): {raw[:300]}")
                return
            if s not in (400, 422):
                print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on leg [{label}]; no defect conclusion")
                return
            named = "offset" in raw.lower()
            print(f"leg {label} OK: rejected with {s} (error names 'offset': {named})")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
