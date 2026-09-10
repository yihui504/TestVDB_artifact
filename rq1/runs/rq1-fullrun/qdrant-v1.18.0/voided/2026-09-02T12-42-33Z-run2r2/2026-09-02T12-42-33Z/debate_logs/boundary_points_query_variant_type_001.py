#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_query_variant_type_001
# strategy: strategy2 type-boundary attack on the `query` oneOf variant
#           domain (BS-01 core target: non-variant scalars, empty object,
#           and double-variant oneOf violations must 400 per
#           behavioral_points_query_001 "400 on an invalid query")
# endpoint: points+query
# constraint_ids: qdrant_type_points_query_001, qdrant_behavioral_points_query_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — serde is assumed to
#            reject query=42 / query="nearest" / query={} / two-variant
#            objects; validation gaps let them through with 200 and
#            undefined downstream behavior)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type x qdrant_type_points_query_001 — the contract
  asserts the `query` field is a oneOf over the variant domain
  {nearest | recommend | discover | context | order_by | fusion | sample |
  neartext | nearimage}. Non-conforming values on a 6-point seeded
  collection (dim 4, Euclid; limit=3 fixed):
    P0   query={"nearest": [V]} (named    -> 200 with >= 1 point (control:
         form control)                          the leg syntax is proven
                                                live before any negative
                                                claim)
    P0b  query=[V] (bare dense array, the  -> 200 with >= 1 point
         documented nearest shorthand)
    T1   query=42 (bare integer — not a   -> 400/422 reject
         PointId position, not a vector)
    T2   query="nearest" (bare string —   -> 400/422 reject
         a variant NAME is not a Query)
    T3   query=true (boolean)             -> 400/422 reject
    T4   query={} (empty object — no      -> 400/422 reject
         variant selected)
    T5   query={"nearest": [V],           -> 400/422 reject (oneOf
         "recommend": {"positive": [1]}}     violation: two variants in
                                              one object; each inner shape
                                              is individually legal per
                                              variant_matrix_001, so the
                                              4xx isolates the oneOf rule)
  NOTE (by-design boundaries, threat model): top-level filter=null is
  treated as no-filter by design — the analogous query=null face is
  covered as a DOCUMENTED equivalence leg in noid_order_001 (id-order),
  not here. SKIPPED: neartext/nearimage variants (inference-based,
  unimplemented per spec WARN per the constraint's own description).
  [chunk_points+query coverage: strategy1+6 limit x range_points_query_001
  (limit_001); strategy1 offset x range_points_query_001 (offset_001);
  strategy1 hnsw_ef x range_points_query_002 (hnswef_001); strategy1
  acorn_scale x range_points_query_002 (acorn_001); strategy2 oneOf-domain
  negative x type_points_query_001 (this script); strategy2 oneOf-domain
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
Oracle: P0/P0b -> 200 with a non-empty points array (control; failure =
  SCRIPT_ERROR-class setup problem, not a defect claim on this constraint);
  T1..T5 -> 400 or 422 per behavioral_points_query_001 "invalid query
  returns 400" (200 = Type1_IllegalSuccess: non-variant query value
  accepted; 5xx with /healthz alive = Type3_RuntimeFailure; transport
  failure -> /healthz re-check then SCRIPT_ERROR) (constraints
  qdrant_type_points_query_001 + qdrant_behavioral_points_query_001).
Constraint: qdrant_type_points_query_001 (bare id) — "query variant domain:
  nearest | recommend | discover | context | order_by | fusion | sample |
  neartext | nearimage (oneOf; neartext/nearimage are inference variants)"
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
    coll = "bpqT1" + tag

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

        def run_leg(label, query_value, expect):
            """expect: 'ok' (200 + points) or 'reject' (400/422)."""
            s, b, raw = safe_request("POST", f"/collections/{coll}/points/query",
                                     json={"query": query_value, "limit": 3}, timeout=60)
            print(f"\nleg {label} -> status={s}")
            print(f"raw: {raw[:400]}")
            if s == -1:
                alive, _, _ = healthz_alive()
                print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion" if alive else
                      "VERDICT: SCRIPT_ERROR — transport failure and healthz down")
                return False
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: "
                          f"returned {s} with service alive: {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return False
            if expect == "ok":
                pts_a, shape = extract_points(b)
                if s != 200 or pts_a is None:
                    print(f"VERDICT: SCRIPT_ERROR — control leg [{label}] failed with {s} "
                          f"({shape}); leg syntax unverifiable, no defect conclusion")
                    return False
                if len(pts_a) < 1:
                    print(f"VERDICT: SCRIPT_ERROR — control leg [{label}] returned 0 points; "
                          f"no defect conclusion")
                    return False
                print(f"leg {label} OK (control): 200 with {len(pts_a)} points (envelope {shape})")
                return True
            # expect == 'reject'
            if s == 200:
                n = len(extract_points(b)[0] or [])
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{label}]: value "
                      f"conforms to NO variant of the oneOf domain (behavioral contract: "
                      f"invalid query returns 400), yet the request was ACCEPTED with 200 "
                      f"({n} points): {raw[:300]}")
                return False
            if s not in (400, 422):
                print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on leg [{label}]; no defect conclusion")
                return False
            print(f"leg {label} OK: rejected with {s}")
            return True

        # Controls first (prove the leg channel live), then the oneOf violations
        steps = (
            ("P0 query={'nearest': [V]} (control)", {"nearest": V}, "ok"),
            ("P0b query=[V] (bare-array shorthand control)", V, "ok"),
            ("T1 query=42", 42, "reject"),
            ("T2 query='nearest' (string)", "nearest", "reject"),
            ("T3 query=true", True, "reject"),
            ("T4 query={} (no variant)", {}, "reject"),
            ("T5 two-variant object nearest+recommend",
             {"nearest": V, "recommend": {"positive": [1]}}, "reject"),
        )
        for label, qv, expect in steps:
            if not run_leg(label, qv, expect):
                return

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
