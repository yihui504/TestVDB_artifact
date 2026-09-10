#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_query_noid_order_001
# strategy: strategy1/semantic attack on the query-absent promise — "query
#           missing without prefetches returns points ordered by their
#           ids" (OpenAPI QueryRequest description) + query=null
#           equivalence + prefetch-only positive closure
# endpoint: points+query
# constraint_ids: qdrant_behavioral_points_query_004
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 + BS-05 (Boundary Default Optimism + semantic drift —
#            the id-order fallback is a documented DEFAULT behavior; a
#            server returning unordered points or erroring on the
#            documented empty query breaks clients that rely on the
#            cheapest scan face)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 x qdrant_behavioral_points_query_004 — the OpenAPI
  QueryRequest description states "query may be omitted when prefetches
  are present; a query missing without prefetches returns points ordered
  by their ids". Legs on a 12-point seeded collection (dim 4, Euclid,
  numeric ids 1..12 so ascending order is total and unambiguous):
    N1  body {"limit": 5} (no query, no     -> 200; points ids ==
         prefetch)                              [1,2,3,4,5] EXACTLY, in
                                               ASCENDING order
    N2  body {} (everything defaulted)      -> 200; <= 10 points (default
                                               limit 10); ids ascending
    N3  body {"query": null, "limit": 5}    -> 200; identical id sequence
         (explicit null == missing — the         to N1 (null is the
         threat-model by-design null face)       documented no-query form)
    N4  prefetch-only (query omitted WITH   -> 200; non-empty points
         prefetch present)                     array; ids a subset of the
                                               seeded 12 (query omission
                                               is LEGAL when prefetches
                                               exist)
  [chunk_points+query coverage: strategy1+6 limit x range_points_query_001
  (limit_001); strategy1 offset x range_points_query_001 (offset_001);
  strategy1 hnsw_ef x range_points_query_002 (hnswef_001); strategy1
  acorn_scale x range_points_query_002 (acorn_001); strategy2 oneOf-domain
  negative x type_points_query_001 (variant_type_001); strategy2 oneOf-domain
  positive closure x type_points_query_001 (variant_matrix_001); strategy2
  invalid-query/filter + 404 x behavioral_points_query_001 (envelope_001);
  strategy7 malformed stream x behavioral_points_query_001 (malformed_001);
  strategy3 by-id vector characteristic mismatch x state_points_query_001
  (byid_dim_001); state by-id missing-point x state_points_query_001
  (byid_stale_001); strategy1 query-absent id-order x
  behavioral_points_query_004 (this script); strategy1 exact=true
  pagination stability x behavioral_points_query_003 (offset_exact_001);
  strategy6 huge-offset resource x behavioral_points_query_002
  (offset_huge_001)]
Oracle: N1 -> 200 with ids exactly [1,2,3,4,5] in ascending order (4xx =
  Type1_IllegalSuccess: documented query-absent request rejected; unsorted
  or wrong ids = Type4_StateLogicViolation: the documented id-order
  promise broken); N2 -> 200 with <= 10 ascending ids; N3 -> 200 with the
  same 5 ids as N1 in ascending order (drift from N1 = Type4: null and
  missing are the same absent-query state); N4 -> 200 with a non-empty
  subset of seeded ids (4xx = Type1: prefetch-present omission is
  explicitly legal); 5xx with /healthz alive = Type3_RuntimeFailure;
  transport failure -> /healthz re-check then SCRIPT_ERROR (constraint
  qdrant_behavioral_points_query_004).
Constraint: qdrant_behavioral_points_query_004 (bare id) — "query may be
  omitted when prefetches are present; a query missing without prefetches
  returns points ordered by their ids" (evidence_tier: explicit; level:
  endpoint)

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
    coll = "bpqN1" + tag

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

        def run(label, body_req):
            s, b, raw = safe_request("POST", f"/collections/{coll}/points/query",
                                     json=body_req, timeout=60)
            print(f"\nleg {label} -> status={s}")
            print(f"raw: {raw[:400]}")
            if s == -1:
                alive, _, _ = healthz_alive()
                print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion" if alive else
                      "VERDICT: SCRIPT_ERROR — transport failure and healthz down")
                return None
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: "
                          f"returned {s} with service alive: {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return None
            pts_a, shape = extract_points(b)
            if s in (400, 422):
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{label}]: the "
                      f"documented query-absent request was REJECTED with {s}: {raw[:300]}")
                return None
            if s != 200 or pts_a is None:
                print(f"VERDICT: SCRIPT_ERROR — unexpected status/envelope {s} ({shape}); no defect conclusion")
                return None
            return pts_a

        # ---- N1: query absent, no prefetch, limit 5 -> ids 1..5 ascending ----
        pts_a = run("N1 no-query no-prefetch limit=5", {"limit": 5})
        if pts_a is None:
            return
        got = [p.get("id") for p in pts_a]
        if got != list(range(1, 6)):
            if sorted(got) == list(range(1, 6)):
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [N1]: "
                      f"documented id-order broken — ids present but NOT ascending: {got} "
                      f"(constraint: points ordered by their ids): {raw[:300]}")
            elif set(got) <= set(range(1, N_SEED + 1)) and len(got) == 5:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [N1]: "
                      f"documented id-order promise broken — expected [1, 2, 3, 4, 5] "
                      f"(smallest 5 ids ascending), got {got}: {raw[:300]}")
            else:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [N1]: "
                      f"expected ids [1, 2, 3, 4, 5], got {got}: {raw[:300]}")
            return
        print("leg N1 OK: ids [1, 2, 3, 4, 5] ascending")

        # ---- N2: fully defaulted body -> <= 10 ascending ----
        pts_a = run("N2 fully defaulted body {}", {})
        if pts_a is None:
            return
        got = [p.get("id") for p in pts_a]
        if not (1 <= len(got) <= 10):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [N2]: default "
                  f"limit is 10 with {N_SEED} points stored, got {len(got)} points: {raw[:300]}")
            return
        if got != sorted(got):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [N2]: ids not "
                  f"ascending ({got}) — documented id-order promise broken: {raw[:300]}")
            return
        if not set(got) <= set(range(1, N_SEED + 1)):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [N2]: ids outside "
                  f"the seeded set: {got}: {raw[:300]}")
            return
        print(f"leg N2 OK: {len(got)} ids ascending: {got}")

        # ---- N3: query=null == missing (documented no-query form) ----
        pts_a = run("N3 query=null limit=5", {"query": None, "limit": 5})
        if pts_a is None:
            return
        got = [p.get("id") for p in pts_a]
        if got != list(range(1, 6)):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [N3]: explicit "
                  f"query=null is the same absent-query state as N1 (threat_model: null "
                  f"means absent), but produced {got} instead of [1, 2, 3, 4, 5] "
                  f"ascending: {raw[:300]}")
            return
        print("leg N3 OK: query=null behaves as missing (ids [1..5] ascending)")

        # ---- N4: prefetch present, query omitted (explicitly legal) ----
        pts_a = run("N4 prefetch-only (query omitted with prefetch)",
                    {"prefetch": [{"query": {"nearest": V}, "limit": 3}], "limit": 3})
        if pts_a is None:
            return
        got = [p.get("id") for p in pts_a]
        if len(got) < 1:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [N4]: prefetch "
                  f"surfaced 0 points although its inner nearest query has 3 hits "
                  f"available: {raw[:300]}")
            return
        if not set(got) <= set(range(1, N_SEED + 1)):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [N4]: ids outside "
                  f"the seeded set: {got}: {raw[:300]}")
            return
        print(f"leg N4 OK: prefetch-only query accepted, {len(got)} points: {got}")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
