#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_query_envelope_001
# strategy: strategy2 invalid-query/filter type-confusion x the endpoint's
#           tri-partite behavioral promise (200 QueryResponse / 400 invalid
#           query / 404 missing collection) with a response-shape oracle on
#           the 200 face
# endpoint: points+query
# constraint_ids: qdrant_behavioral_points_query_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 + BS-05 (Parameter Type Coercion Trust + nested filter
#            validation — filter.should=<object>/must_not=<string>/
#            must=<int>/min_should.conditions=<string> are assumed to be
#            rejected by serde; validation gaps accept them with 200)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 x qdrant_behavioral_points_query_001 — the endpoint
  promise is tri-partite: "valid query returns HTTP 200 with result array
  of scored points and optional next_page_offset; invalid query returns
  400; missing collection returns 404". Legs on a 6-point seeded
  collection (dim 4, Euclid; payload city: berlin x3 / paris x3):
    V200  valid nearest query                -> 200; envelope carries the
          points array (contract response_shape: result object ->
          result.points[]); every point has an id and a numeric score;
          status is a string; time is a number
    Vnull filter=null                        -> 200 with the SAME result
          set as the no-filter query (by-design per threat_model:
          null means no-filter — asserted as documented EQUIVALENCE, no
          defect claim)
    V400a filter={"should": <object>}        -> 400 (array position
          occupied by an object — true type violation, NOT nullable-None)
    V400b filter={"must_not": "city"}        -> 400 (string in array
          position)
    V400c filter={"must": 123}               -> 400 (integer in array
          position)
    V400d filter={"min_should":              -> 400 (BS-05 focus:
          {"conditions": "city",                required paths present
          "min_count": 1}}                      (conditions + min_count)
                                                 but conditions is a
                                                 string, not an array)
    V404  same valid query against a         -> EXACTLY 404 (missing
          never-created collection             collection face)
  [chunk_points+query coverage: strategy1+6 limit x range_points_query_001
  (limit_001); strategy1 offset x range_points_query_001 (offset_001);
  strategy1 hnsw_ef x range_points_query_002 (hnswef_001); strategy1
  acorn_scale x range_points_query_002 (acorn_001); strategy2 oneOf-domain
  negative x type_points_query_001 (variant_type_001); strategy2 oneOf-domain
  positive closure x type_points_query_001 (variant_matrix_001); strategy2
  invalid-query/filter + 404 x behavioral_points_query_001 (this script);
  strategy7 malformed stream x behavioral_points_query_001 (malformed_001);
  strategy3 by-id vector characteristic mismatch x state_points_query_001
  (byid_dim_001); state by-id missing-point x state_points_query_001
  (byid_stale_001); strategy1 query-absent id-order x
  behavioral_points_query_004 (noid_order_001); strategy1 exact=true
  pagination stability x behavioral_points_query_003 (offset_exact_001);
  strategy6 huge-offset resource x behavioral_points_query_002
  (offset_huge_001)]
Oracle: V200 -> 200 with result.points[] a non-empty array whose elements
  each carry an id and a numeric score (response_shape result.points[].id
  any / .score number), plus string status and number time (missing points
  array or non-numeric score = Type4_StateLogicViolation); Vnull -> 200
  with the identical id set as the no-filter leg; V400a..V400d -> 400 or
  422 (200 = Type1_IllegalSuccess: type-violating filter accepted); V404 ->
  exactly 404 (200 = Type1_IllegalSuccess phantom-collection success; 400 =
  wrong error face; 5xx with /healthz alive = Type3_RuntimeFailure;
  transport failure -> /healthz re-check then SCRIPT_ERROR) (constraint
  qdrant_behavioral_points_query_001).
Constraint: qdrant_behavioral_points_query_001 (bare id) — "returns 200
  QueryResponse {result: [ScoredPoint], next_page_offset?}; 400 on an
  invalid query; 404 when the collection is missing" (evidence_tier:
  explicit; level: endpoint)

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
    coll = "bpqV1" + tag

    # Arrange: own collection, own data, own cleanup
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        pts = [{"id": i, "vector": [v * (1.0 + i / 100.0) for v in V],
                "payload": {"city": "berlin" if i <= 3 else "paris"}}
               for i in range(1, N_SEED + 1)]
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": pts}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return

        # ---- Leg V200: valid query -> 200 + response_shape oracle ----
        s, b, raw = safe_request("POST", f"/collections/{coll}/points/query",
                                 json={"query": {"nearest": V}, "limit": N_SEED}, timeout=60)
        print(f"\nleg V200 valid -> status={s}")
        print(f"raw: {raw[:500]}")
        if s == -1:
            alive, _, _ = healthz_alive()
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion" if alive else
                  "VERDICT: SCRIPT_ERROR — transport failure and healthz down")
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [V200]: valid query "
                      f"returned {s} with service alive: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
            return
        pts_a, shape = extract_points(b)
        if s != 200 or pts_a is None:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [V200]: valid documented "
                  f"query rejected/malformed with {s} (envelope {shape}): {raw[:300]}")
            return
        if len(pts_a) != N_SEED:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [V200]: {N_SEED} "
                  f"points seeded, limit={N_SEED}, got {len(pts_a)}: {raw[:300]}")
            return
        for p in pts_a:
            if "id" not in p:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [V200]: "
                      f"ScoredPoint without id: {json.dumps(p)[:200]}")
                return
            sc = p.get("score")
            if not isinstance(sc, (int, float)) or isinstance(sc, bool):
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [V200]: "
                      f"ScoredPoint id={p.get('id')} score is not numeric ({sc!r}) "
                      f"(response_shape: result.points[].score number): {raw[:300]}")
                return
        if not isinstance(b.get("status"), str):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [V200]: response "
                  f"status field is not a string (response_shape: status string): {raw[:200]}")
            return
        if not isinstance(b.get("time"), (int, float)):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [V200]: response "
                  f"time field is not a number (response_shape: time number): {raw[:200]}")
            return
        baseline_ids = sorted(p.get("id") for p in pts_a)
        print(f"leg V200 OK: envelope {shape}, {len(pts_a)} ScoredPoints, shape fields conform")

        # ---- Leg Vnull: filter=null == no-filter (by-design; equivalence only) ----
        s, b, raw = safe_request("POST", f"/collections/{coll}/points/query",
                                 json={"query": {"nearest": V}, "limit": N_SEED,
                                       "filter": None}, timeout=60)
        print(f"\nleg Vnull filter=null -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            alive, _, _ = healthz_alive()
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion" if alive else
                  "VERDICT: SCRIPT_ERROR — transport failure and healthz down")
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [Vnull]: "
                      f"filter=null returned {s} with service alive: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
            return
        pts_a, _ = extract_points(b)
        if s != 200 or pts_a is None or sorted(p.get("id") for p in pts_a) != baseline_ids:
            print(f"OBSERVATION (no defect claim — threat_model marks filter=null handling "
                  f"by-design): filter=null did not behave as no-filter (status={s}): "
                  f"{raw[:300]}")
        else:
            print("leg Vnull OK: filter=null equivalent to no-filter (documented by-design)")

        # ---- Legs V400a..V400d: type-violating filters -> must 400/422 ----
        bad_filters = (
            ("V400a should=<object>",
             {"should": {"key": "city", "match": {"value": "berlin"}}}),
            ("V400b must_not='city' (string)", {"must_not": "city"}),
            ("V400c must=123 (int)", {"must": 123}),
            ("V400d min_should.conditions='city' (string)",
             {"min_should": {"conditions": "city", "min_count": 1}}),
        )
        for label, filt in bad_filters:
            s, b, raw = safe_request("POST", f"/collections/{coll}/points/query",
                                     json={"query": {"nearest": V}, "limit": 3,
                                           "filter": filt}, timeout=60)
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
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: "
                          f"type-violating filter returned {s} (must be a clean 4xx) with "
                          f"service alive: {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return
            if s == 200:
                n = len(extract_points(b)[0] or [])
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{label}]: a Filter "
                      f"clause array position is occupied by a non-array value "
                      f"(behavioral contract: invalid query returns 400), yet the request "
                      f"was ACCEPTED with 200 ({n} points): {raw[:300]}")
                return
            if s not in (400, 422):
                print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on leg [{label}]; no defect conclusion")
                return
            print(f"leg {label} OK: rejected with {s}")

        # ---- Leg V404: missing collection -> EXACTLY 404 ----
        ghost = "bpqV1ghost" + tag
        s, b, raw = safe_request("POST", f"/collections/{ghost}/points/query",
                                 json={"query": {"nearest": V}, "limit": 3}, timeout=60)
        print(f"\nleg V404 missing collection -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            alive, _, _ = healthz_alive()
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion" if alive else
                  "VERDICT: SCRIPT_ERROR — transport failure and healthz down")
            return
        if s != 404:
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [V404]: missing "
                          f"collection returned {s} with service alive: {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [V404]: behavioral "
                  f"contract promises EXACTLY 404 for a missing collection, got {s}: "
                  f"{raw[:300]}")
            return
        print("leg V404 OK: exactly 404")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
