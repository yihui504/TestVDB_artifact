#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_query_byid_stale_001
# strategy: state-consistency attack on the by-id stored-vector promise —
#           positive ids that NEVER EXISTED and ids DELETED after upsert
#           must produce a clean error (no stored vector exists to fetch),
#           never a silent 200 with fabricated scores nor a 5xx
# endpoint: points+query
# constraint_ids: qdrant_state_points_query_001
# source_url: https://qdrant.tech/documentation/search/search/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-03 (Concurrency State Blindness — the by-id join is
#            assumed to be guarded; stale/missing references that fall
#            through produce phantom vectors or crash the resolver)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: state x qdrant_state_points_query_001 — "by-id query uses the
  referenced point's stored vector" implies the referenced point MUST
  exist; when it does not, the request cannot fulfill its contract and
  must error. Legs on one OWN collection (dim 4, Euclid, ids 1..3 + one
  UUID point; id 7 is upserted then DELETED so the reference is stale
  against real segment state, not merely absent):
    S0  positive [1] (existing id)        -> 200 (by-id mechanism control)
    S3  positive [<existing UUID>]        -> 200 (PointId oneOf uuid face
                                              per contract data_types
                                              "a UUID string can be used
                                              instead of a numeric ID")
    S1  positive [999999] (never          -> 4xx error (no stored vector
        existed)                              to fetch); 200 = Type1
                                              (phantom vector scored);
                                              5xx = Type3
    S2  positive [7] (upserted then       -> 4xx error (stale reference
        deleted)                              against post-delete state)
    S4  positive [1, 999999] (mixed)      -> 4xx error (ANY missing member
                                              breaks the by-id contract)
  Rationale for the mutation point (G6): deletion is the state transition
  that most cleanly invalidates a by-id join — the reference is
  well-formed and previously valid, so type validation cannot catch it;
  only true segment-state reconciliation can.
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
  (this script); strategy1 query-absent id-order x
  behavioral_points_query_004 (noid_order_001); strategy1 exact=true
  pagination stability x behavioral_points_query_003 (offset_exact_001);
  strategy6 huge-offset resource x behavioral_points_query_002
  (offset_huge_001)]
Oracle: S0/S3 -> 200 with a non-empty points array (positive pairing);
  S1/S2/S4 -> 400/404/422 clean error (200 with scored results =
  Type1_IllegalSuccess — a by-id fetch with no stored vector silently
  fabricated input; 5xx with /healthz alive = Type3_RuntimeFailure —
  resolver crash instead of a clean error; transport failure ->
  /healthz re-check then SCRIPT_ERROR) (constraint
  qdrant_state_points_query_001).
Constraint: qdrant_state_points_query_001 (bare id) — "by-id query uses
  the referenced point's stored vector; if it does not match the using
  vector characteristics the request errors" (evidence_tier: explicit;
  level: system)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+query        -> POST /collections/{collection_name}/points/query
  points+upsert       -> PUT  /collections/{collection_name}/points
  points+delete       -> POST /collections/{collection_name}/points/delete
  collections+create  -> PUT  /collections/{collection_name}
  collections+delete  -> DELETE /collections/{collection_name}
  healthz             -> GET  /healthz
  (wait is a query parameter on the write faces — passed via params=)
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
    coll = "bpqS1" + tag
    uid = str(uuid.uuid4())

    # Arrange: own collection, own data (incl. a UUID-id point), own cleanup
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        pts = ([{"id": i, "vector": [v * (1.0 + i / 100.0) for v in V]} for i in (1, 2, 3)]
               + [{"id": uid, "vector": V}, {"id": 7, "vector": V}])
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": pts}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return
        # make id 7 a STALE reference: delete it durably before querying
        s, _, raw = safe_request("POST", f"/collections/{coll}/points/delete",
                                 json={"points": [7]}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup delete-7 failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return

        def leg(label, positive, expect):
            s, b, raw = safe_request("POST", f"/collections/{coll}/points/query",
                                     json={"query": {"recommend": {"positive": positive}},
                                           "limit": 3}, timeout=60)
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
                          f"returned {s} with service alive (missing by-id reference must be "
                          f"a CLEAN error, not a crash): {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return False
            if expect == "ok":
                pts_a, shape = extract_points(b)
                if s != 200 or pts_a is None:
                    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{label}]: valid "
                          f"by-id recommend rejected/malformed with {s}: {raw[:300]}")
                    return False
                if len(pts_a) < 1:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [{label}]: "
                          f"points seeded, limit=3, got 0 points: {raw[:300]}")
                    return False
                print(f"leg {label} OK: 200 with {len(pts_a)} points (envelope {shape})")
                return True
            # expect == 'error'
            if s == 200:
                n = len(extract_points(b)[0] or [])
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{label}]: the "
                      f"positive set references a point with NO stored vector (never existed "
                      f"or deleted), so no by-id fetch can fulfill the query, yet it was "
                      f"ACCEPTED with 200 ({n} points scored from a phantom vector): "
                      f"{raw[:300]}")
                return False
            if s in (400, 404, 422):
                print(f"leg {label} OK: clean error {s}")
                return True
            print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on leg [{label}]; no defect conclusion")
            return False

        ok = True
        ok &= leg("S0 existing numeric id (control)", [1], "ok")
        ok &= leg("S3 existing UUID id (PointId oneOf face)", [uid], "ok")
        ok &= leg("S1 never-existed id 999999", [999999], "error")
        ok &= leg("S2 upserted-then-deleted id 7", [7], "error")
        ok &= leg("S4 mixed [1, 999999]", [1, 999999], "error")
        if not ok:
            return

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
