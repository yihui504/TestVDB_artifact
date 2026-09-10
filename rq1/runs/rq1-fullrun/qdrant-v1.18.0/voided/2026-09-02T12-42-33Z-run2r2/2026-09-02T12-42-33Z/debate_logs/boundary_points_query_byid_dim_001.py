#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_query_byid_dim_001
# strategy: strategy3 dimension/characteristic-mismatch attack x the by-id
#           stored-vector state constraint (lookup_from resolving a point
#           whose stored vector does not match the using vector's
#           characteristics must ERROR, never succeed silently nor crash)
# endpoint: points+query
# constraint_ids: qdrant_state_points_query_001
# source_url: https://qdrant.tech/documentation/search/search/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-02 (Error Message Negligence — dimension-mismatched
#            by-id lookups are assumed to error cleanly; a silent 200 with
#            cross-dimension garbage scores corrupts every downstream
#            recommendation)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy3 x qdrant_state_points_query_001 — the contract asserts
  "by-id query uses the referenced point's stored vector; if it does not
  match the using vector characteristics the request errors". The by-id
  face of POST /collections/{c}/points/query is exercised through
  recommend.positive resolved via lookup_from on four OWN collections:
    A  (dim 4, unnamed, ids 1..3)  — the searching collection
    A2 (dim 4, unnamed, id 1)      — matching-characteristics lookup target
    B  (dim 8, unnamed, id 1)      — MISMATCHED-characteristics target
    N  (named v4 size 4 + v8 size 8, id 1 carries both) — named-vector
                                     characteristic face
  Legs (query = recommend over A unless stated):
    C2  positive [1], no lookup_from            -> 200 (same-collection
                                                   by-id fetch, control)
    C1  positive [1], lookup_from A2            -> 200 with >= 1 point
                                                   (matching dim 4 == 4)
    M1  positive [1], lookup_from B             -> 4xx ERROR (stored
                                                   vector dim 8 does not
                                                   match using dim 4);
                                                   200 = Type1 (mismatch
                                                   silently scored);
                                                   5xx = Type3
    M2  on N with using="v4", positive [1],
        lookup_from {collection: N, vector:"v8"} -> 4xx ERROR (lookup
                                                   resolves v8 dim 8
                                                   against the v4 index)
  Rationale for the mutation point (G6): the lookup seam is the ONLY place
  where a stored vector crosses collection boundaries — the dimension
  check is a pure runtime join condition with no compile-time guard, the
  classic spot where an assume-valid join produces cross-domain garbage.
  [chunk_points+query coverage: strategy1+6 limit x range_points_query_001
  (limit_001); strategy1 offset x range_points_query_001 (offset_001);
  strategy1 hnsw_ef x range_points_query_002 (hnswef_001); strategy1
  acorn_scale x range_points_query_002 (acorn_001); strategy2 oneOf-domain
  negative x type_points_query_001 (variant_type_001); strategy2 oneOf-domain
  positive closure x type_points_query_001 (variant_matrix_001); strategy2
  invalid-query/filter + 404 x behavioral_points_query_001 (envelope_001);
  strategy7 malformed stream x behavioral_points_query_001 (malformed_001);
  strategy3 by-id vector characteristic mismatch x state_points_query_001
  (this script); state by-id missing-point x state_points_query_001
  (byid_stale_001); strategy1 query-absent id-order x
  behavioral_points_query_004 (noid_order_001); strategy1 exact=true
  pagination stability x behavioral_points_query_003 (offset_exact_001);
  strategy6 huge-offset resource x behavioral_points_query_002
  (offset_huge_001)]
Oracle: C2/C1 -> 200 with a non-empty points array (positive pairing: the
  by-id mechanism itself must work before any mismatch claim); M1/M2 ->
  400/404/422 error (the contract's "the request errors" face; 200 with a
  scored result = Type1_IllegalSuccess — characteristics mismatch silently
  accepted; 5xx with /healthz alive = Type3_RuntimeFailure — crash instead
  of a clean error; transport failure -> /healthz re-check then
  SCRIPT_ERROR) (constraint qdrant_state_points_query_001).
Constraint: qdrant_state_points_query_001 (bare id) — "by-id query uses
  the referenced point's stored vector; if it does not match the using
  vector characteristics the request errors" (evidence_tier: explicit;
  level: system)

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

V4 = [0.5, 0.25, 0.125, 0.0625]
V8 = [0.5, 0.25, 0.125, 0.0625, 0.03125, 0.015625, 0.0078125, 0.00390625]


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
    coll_a = "bpqD1a" + tag   # searching collection, dim 4
    coll_a2 = "bpqD1b" + tag  # matching lookup target, dim 4
    coll_b = "bpqD1c" + tag   # mismatched lookup target, dim 8
    coll_n = "bpqD1d" + tag   # named-vector characteristic face

    created = []

    def create(name, vectors, points):
        s, _, raw = safe_request("PUT", f"/collections/{name}",
                                 json={"vectors": vectors}, timeout=60)
        if s not in (200, 201):
            print(f"setup create {name} failed status={s}: {raw[:300]}")
            return False
        created.append(name)
        s, _, raw = safe_request("PUT", f"/collections/{name}/points",
                                 json={"points": points}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert {name} failed status={s}: {raw[:300]}")
            return False
        return True

    try:
        if not create(coll_a, {"size": 4, "distance": "Euclid"},
                      [{"id": i, "vector": [v * (1.0 + i / 100.0) for v in V4]} for i in (1, 2, 3)]):
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return
        if not create(coll_a2, {"size": 4, "distance": "Euclid"},
                      [{"id": 1, "vector": V4}]):
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return
        if not create(coll_b, {"size": 8, "distance": "Euclid"},
                      [{"id": 1, "vector": V8}]):
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return
        if not create(coll_n, {"v4": {"size": 4, "distance": "Euclid"},
                               "v8": {"size": 8, "distance": "Euclid"}},
                      [{"id": 1, "vector": {"v4": V4, "v8": V8}}]):
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return

        def leg(label, coll, body, expect):
            s, b, raw = safe_request("POST", f"/collections/{coll}/points/query",
                                     json=body, timeout=60)
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
                          f"returned {s} with service alive (characteristic mismatch must be "
                          f"a CLEAN error, not a crash): {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return False
            if expect == "ok":
                pts_a, shape = extract_points(b)
                if s != 200 or pts_a is None:
                    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{label}]: "
                          f"valid by-id recommend rejected/malformed with {s}: {raw[:300]}")
                    return False
                if len(pts_a) < 1:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg "
                          f"[{label}]: 3 points seeded, limit=3, got 0 points: {raw[:300]}")
                    return False
                print(f"leg {label} OK: 200 with {len(pts_a)} points (envelope {shape})")
                return True
            # expect == 'error'
            if s == 200:
                n = len(extract_points(b)[0] or [])
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{label}]: the "
                      f"by-id lookup resolves a stored vector whose characteristics do NOT "
                      f"match the using vector (contract: the request errors), yet it was "
                      f"ACCEPTED with 200 ({n} cross-characteristic points scored): "
                      f"{raw[:300]}")
                return False
            if s in (400, 404, 422):
                print(f"leg {label} OK: clean error {s}")
                return True
            print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on leg [{label}]; no defect conclusion")
            return False

        ok = True
        ok &= leg("C2 same-collection by-id (control)",
                  coll_a, {"query": {"recommend": {"positive": [1]}}, "limit": 3}, "ok")
        ok &= leg("C1 lookup_from matching dim4==dim4",
                  coll_a, {"query": {"recommend": {"positive": [1]}}, "limit": 3,
                           "lookup_from": {"collection": coll_a2}}, "ok")
        ok &= leg("M1 lookup_from mismatched dim8 vs dim4",
                  coll_a, {"query": {"recommend": {"positive": [1]}}, "limit": 3,
                           "lookup_from": {"collection": coll_b}}, "error")
        ok &= leg("M2 named-vector lookup v8 against v4 index",
                  coll_n, {"query": {"recommend": {"positive": [1]}}, "using": "v4",
                           "limit": 3,
                           "lookup_from": {"collection": coll_n, "vector": "v8"}}, "error")
        if not ok:
            return

        print("VERDICT: NO_DEFECT")
    finally:
        for name in list(created):
            try:
                safe_request("DELETE", f"/collections/{name}", timeout=60)
            except Exception:
                pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
