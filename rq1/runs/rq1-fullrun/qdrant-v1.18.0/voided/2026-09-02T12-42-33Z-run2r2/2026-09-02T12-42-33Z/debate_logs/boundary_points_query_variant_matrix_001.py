#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_query_variant_matrix_001
# strategy: strategy2 oneOf-domain POSITIVE closure (G4: every variant the
#           constraint enumerates must execute 200 on the unified query
#           face — proves the domain claim so later negative faces rest on
#           a proven-live positive matrix)
# endpoint: points+query
# constraint_ids: qdrant_type_points_query_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — the variant list is
#            trusted as implemented; a variant that 400s on its documented
#            shape strands the documented capability silently)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 positive closure x qdrant_type_points_query_001 — every
  locally-testable variant of the enumerated oneOf domain is executed once
  on POST /collections/{c}/points/query (6-point seeded collection, dim 4,
  Euclid, payload ts=1000..6000 for order_by):
    M1 nearest   {"query": {"nearest": [V]}}                       -> 200
    M2 recommend {"query": {"recommend": {"positive": [1, 2]}}}    -> 200
         (by-id stored-vector fetch — also the positive face for
          state_points_query_001, cross-referenced in byid_dim_001)
    M3 discover  {"query": {"discover": {"target": 1}}}            -> 200
    M4 context   {"query": {"context": {"context":                -> 200
         [{"positive": 1, "negative": 2}]}}
    M5 order_by  {"query": {"order_by": "ts"}, "limit": 6}         -> 200
    M6 fusion    prefetch[2] + {"query": {"fusion": "rrf"}}        -> 200
         (dual-form tolerance: if the string shorthand is not accepted,
          the object form {"rrf": {}} is tried; EITHER 200 = pass —
          isolates the variant capability from spelling drift)
    M7 sample    {"query": {"sample": "random"}, "limit": 3}       -> 200
         (dual-form tolerance: {"sample": {"random": {}}} fallback)
  SKIPPED: by-design per threat_model — neartext/nearimage variants
  (inference-based, unimplemented per the constraint's own spec WARN;
  no inference provider is configured in the sandbox).
  [chunk_points+query coverage: strategy1+6 limit x range_points_query_001
  (limit_001); strategy1 offset x range_points_query_001 (offset_001);
  strategy1 hnsw_ef x range_points_query_002 (hnswef_001); strategy1
  acorn_scale x range_points_query_002 (acorn_001); strategy2 oneOf-domain
  negative x type_points_query_001 (variant_type_001); strategy2 oneOf-domain
  positive closure x type_points_query_001 (this script); strategy2
  invalid-query/filter + 404 x behavioral_points_query_001 (envelope_001);
  strategy7 malformed stream x behavioral_points_query_001 (malformed_001);
  strategy3 by-id vector characteristic mismatch x state_points_query_001
  (byid_dim_001); state by-id missing-point x state_points_query_001
  (byid_stale_001); strategy1 query-absent id-order x
  behavioral_points_query_004 (noid_order_001); strategy1 exact=true
  pagination stability x behavioral_points_query_003 (offset_exact_001);
  strategy6 huge-offset resource x behavioral_points_query_002
  (offset_huge_001)]
Oracle: M1..M7 -> HTTP 200 with a non-empty points array of ScoredPoints
  (each element carries an id; result.points[] per contract
  response_shape); M5 returns all 6 seeded ids; any 4xx on a documented
  variant shape = Type1_IllegalSuccess (documented capability rejected);
  200 with an empty points array = Type4_StateLogicViolation (6 points
  seeded, variant must surface them); 5xx with /healthz alive =
  Type3_RuntimeFailure; transport failure -> /healthz re-check then
  SCRIPT_ERROR (constraint qdrant_type_points_query_001).
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
    coll = "bpqM1" + tag

    # Arrange: own collection, own data (payload ts for order_by), own cleanup
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        pts = [{"id": i, "vector": [v * (1.0 + i / 100.0) for v in V],
                "payload": {"ts": 1000 * i}} for i in range(1, N_SEED + 1)]
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": pts}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return

        def check(label, body_req, min_pts=1, want_ids=None, alt=None):
            """Run one variant leg; alt = alternative documented spelling to try
            if the primary spelling does not return 200."""
            for attempt, req in enumerate((body_req, alt) if alt else (body_req,)):
                s, b, raw = safe_request("POST", f"/collections/{coll}/points/query",
                                         json=req, timeout=60)
                print(f"\nleg {label} (form {attempt + 1}) -> status={s}")
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
                              f"variant returned {s} with service alive: {raw[:300]}")
                    else:
                        print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                    return False
                pts_a, shape = extract_points(b)
                if s == 200 and pts_a is not None:
                    if len(pts_a) < min_pts:
                        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg "
                              f"[{label}]: {N_SEED} points seeded but variant surfaced "
                              f"{len(pts_a)} (< {min_pts}): {raw[:300]}")
                        return False
                    if want_ids is not None:
                        got_ids = sorted(p.get("id") for p in pts_a)
                        if got_ids != sorted(want_ids):
                            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg "
                                  f"[{label}]: expected ids {sorted(want_ids)}, got "
                                  f"{got_ids}: {raw[:300]}")
                            return False
                    print(f"leg {label} OK: 200, {len(pts_a)} points (envelope {shape})")
                    return True
                if alt and attempt == 0:
                    print(f"primary spelling not accepted ({s}); trying alternative "
                          f"documented spelling")
                    continue
                if s in (400, 422):
                    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{label}]: "
                          f"documented variant shape rejected with {s} (all accepted "
                          f"spellings exhausted): {raw[:300]}")
                    return False
                print(f"VERDICT: SCRIPT_ERROR — unexpected status/envelope {s} on leg "
                      f"[{label}]; no defect conclusion")
                return False
            return False

        ok = True
        ok &= check("M1 nearest (named form)",
                    {"query": {"nearest": V}, "limit": 3})
        ok &= check("M2 recommend (positive by-id)",
                    {"query": {"recommend": {"positive": [1, 2]}}, "limit": 3})
        ok &= check("M3 discover (target by-id)",
                    {"query": {"discover": {"target": 1}}, "limit": 3})
        ok &= check("M4 context (pair)",
                    {"query": {"context": {"context": [
                        {"positive": 1, "negative": 2}]}}, "limit": 3})
        ok &= check("M5 order_by (payload key ts)",
                    {"query": {"order_by": "ts"}, "limit": N_SEED},
                    min_pts=N_SEED, want_ids=list(range(1, N_SEED + 1)))
        ok &= check("M6 fusion rrf (prefetch x2)",
                    {"prefetch": [
                        {"query": {"nearest": V}, "limit": 3},
                        {"query": {"recommend": {"positive": [1]}}, "limit": 3}],
                     "query": {"fusion": "rrf"}, "limit": 3},
                    alt={"prefetch": [
                        {"query": {"nearest": V}, "limit": 3},
                        {"query": {"recommend": {"positive": [1]}}, "limit": 3}],
                         "query": {"fusion": {"rrf": {}}}, "limit": 3})
        ok &= check("M7 sample (random)",
                    {"query": {"sample": "random"}, "limit": 3},
                    alt={"query": {"sample": {"random": {}}}, "limit": 3})
        if not ok:
            return

        print("SKIPPED: neartext/nearimage variants — by-design per threat_model "
              "(inference-based, unimplemented per the constraint's spec WARN)")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
