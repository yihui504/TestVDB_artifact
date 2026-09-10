#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_recommend_resource_010
# strategy: strategy6 resource-limit probe (Type3_RuntimeFailure class) on
#           the recommend face — CONSERVATIVE ladder per the R11/R41
#           reflection lessons: single-parameter extremes first, ONE
#           modest product rung, NO escalation beyond (an OOM voids the
#           whole round — 23 scripts died with the container in R41)
# endpoint: points+recommend
# constraint_ids: qdrant_range_points_recommend_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/search/recommend-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — the contract bounds
#            limit/hnsw_ef only from BELOW; clients trust the
#            implementation clamps huge values instead of preallocating
#            from them — the R11 proven OOM shape was an allocator
#            capacity driven by an extreme product)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy6 resource x qdrant_range_points_recommend_001 — the
  contract bounds limit only from below (minimum 1) and documents no
  maximum for limit or params.hnsw_ef on the recommend face; the
  resource class probes the implementation's UPPER behavior on a
  12-point seeded collection (dim 4, Euclid, binary-exact — R27),
  conservative ladder first (R11/R41 lessons):
    G    guard: limit=3 baseline               -> 200 with <= 3 points
         (face liveness before any extreme leg)
    R1   SINGLE extreme: limit=999999999       -> 200 with <= 12 points
         (limit is an upper bound; returning   or clean 400/422
         fewer is legal)
    R2   SINGLE extreme: params.hnsw_ef=       -> same expectation
         1000000, limit=10
    R3   MODEST product rung: limit=10000 x    -> same expectation
         params.hnsw_ef=10000 (product 1e8 — three orders below
         the R11 killer product 1e12; escalation only in a later
         round if this rung signals)
  Key (strategy6 differs from strategy1): 200 accepting a huge value is
  NOT a defect; the defect signal is a CRASH — 5xx, OOM/panic text,
  connection reset, a transport failure while /healthz stays alive
  (hang), or REQUEST-TRIGGERED SERVER DEATH: transport death on an
  extreme leg with /healthz DOWN afterward (R11 framing — the
  resource_bound violation itself, not a script error).
  [chunk_points+recommend coverage (11 scripts): strategy1 limit boundary
  matrix x qdrant_range_points_recommend_001 (limit_001); strategy1 offset
  boundary matrix + huge-offset x qdrant_range_points_recommend_001
  (offset_002); behavioral positive core by-id/by-vector/strategy-enum
  closure x qdrant_behavioral_points_recommend_001 (positive_003); BS-10
  missing referenced point ids 400-legs x qdrant_behavioral_points_
  recommend_001 (missing_ref_004); using-vector characteristics mismatch
  (lookup dim + named partial) x qdrant_behavioral_points_recommend_001
  (using_mismatch_005); 404 status-mapping legs x qdrant_behavioral_
  points_recommend_001 (404_006); strategy2 RecommendExample oneOf element
  type-confusion + raw-vector dimension x qdrant_behavioral_points_
  recommend_001 (example_type_007); R33/R40 dual-key silent-drop family on
  mixed recommend examples x qdrant_behavioral_points_recommend_001
  (dualkey_008); strategy2 filter type-confusion family mirror x
  qdrant_behavioral_points_recommend_001 (filter_type_009); strategy6
  conservative single-extreme + modest-product resource x
  qdrant_range_points_recommend_001 (this script); strategy7 malformed
  raw-byte stream x qdrant_behavioral_points_recommend_001
  (malformed_011)]
Oracle: noise guard -> /healthz 200 BEFORE any extreme leg (down =
  SCRIPT_ERROR, environment noise); G -> 200 with <= 3 points (other =
  SCRIPT_ERROR, face not live); R1/R2/R3 -> each 200 with <= 12 points or
  a clean 400/422 (either disposition is the resource-class norm);
  DEFECT (Type3_RuntimeFailure) on 5xx with /healthz alive, on OOM/panic/
  capacity-overflow text in the body, on transport failure with
  /healthz alive (hang/DoS), and on transport death during an extreme leg
  with /healthz DOWN after it — server killed by the request
  (resource_bound; R11 framing); DEFECT (Type4_StateLogicViolation) if a
  200 returns MORE than the 12 stored points (constraint
  qdrant_range_points_recommend_001).
Constraint: qdrant_range_points_recommend_001 (bare id) — "limit minimum 1
  (required); offset minimum 0" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+recommend      -> POST /collections/{collection_name}/points/recommend
  points+upsert         -> PUT  /collections/{collection_name}/points
  collections+create    -> PUT  /collections/{collection_name}
  collections+delete    -> DELETE /collections/{collection_name}
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
N_SEED = 12
V = [0.5, 0.25, 0.125, 0.0625]


def safe_request(method, endpoint, json=None, timeout=60, params=None):
    """Safe HTTP wrapper -> (status_code, body, raw_text); transport failure -> (-1, err, err)."""
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
    hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
    return hs == 200, hs, str(hraw)[:200]


def extract_scored(body):
    """Contract response_shape: result is a top-level array of ScoredPoints."""
    if not isinstance(body, dict):
        return None, "body-not-dict"
    result = body.get("result")
    if isinstance(result, list):
        return result, "result-array"
    return None, "result-missing-or-not-array"


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bprR10" + tag

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

        # ---- noise guard: healthy BEFORE any extreme leg (R41 lesson) ----
        alive, hs, hraw = healthz_alive()
        if not alive:
            print(f"noise guard: /healthz down BEFORE any extreme leg ({hs}: {hraw})")
            print("VERDICT: SCRIPT_ERROR — environment not healthy before extreme legs")
            return
        print("noise guard OK: /healthz 200 before extreme legs")

        # ---- Leg G: face-liveness baseline ----
        s, b, raw = safe_request("POST", f"/collections/{coll}/points/recommend",
                                 json={"positive": [1], "limit": 3, "params": {"exact": True}},
                                 timeout=60)
        print(f"\nleg G limit=3 baseline -> status={s}")
        print(f"raw: {raw[:300]}")
        scored, shape = extract_scored(b)
        if s != 200 or scored is None or len(scored) > 3:
            print(f"VERDICT: SCRIPT_ERROR — baseline face not live ({s}, {shape}); no defect conclusion")
            return
        print(f"leg G OK: {len(scored)} points returned")

        # ---- Legs R1/R2/R3: conservative extreme ladder ----
        r_legs = (
            ("R1 single extreme limit=999999999",
             {"positive": [1], "limit": 999999999}),
            ("R2 single extreme hnsw_ef=1000000",
             {"positive": [1], "limit": 10, "params": {"hnsw_ef": 1000000}}),
            ("R3 modest product limit=10000 x hnsw_ef=10000",
             {"positive": [1], "limit": 10000, "params": {"hnsw_ef": 10000}}),
        )
        for label, payload in r_legs:
            s, b, raw = safe_request("POST", f"/collections/{coll}/points/recommend",
                                     json=payload, timeout=180)
            print(f"\nleg {label} -> status={s}")
            print(f"raw: {raw[:400]}")
            if s == -1:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: request "
                          f"did not complete (transport error) while /healthz is alive "
                          f"(hang/DoS signal)")
                else:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: "
                          f"transport death during an extreme leg with /healthz DOWN after it — "
                          f"server killed by the request (resource_bound; R11 framing)")
                return
            low = raw.lower()
            crash_tokens = [k for k in ("oom", "out of memory", "panic", "capacity overflow",
                                        "killed", "allocation") if k in low]
            if crash_tokens and 500 <= s <= 599:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: {s} with "
                      f"crash tokens {crash_tokens}: {raw[:300]}")
                return
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: extreme "
                          f"value returned {s} with service alive (OOM/DoS): {raw[:300]}")
                else:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: {s} "
                          f"and /healthz DOWN after the extreme leg — server killed by the "
                          f"request (resource_bound; R11 framing)")
                return
            if s in (200, 201):
                scored, shape = extract_scored(b)
                if scored is None:
                    print(f"VERDICT: SCRIPT_ERROR — 200 but no result array ({shape}); no defect conclusion")
                    return
                if len(scored) > N_SEED:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [{label}]: "
                          f"only {N_SEED} points exist but {len(scored)} returned: {raw[:300]}")
                    return
                print(f"leg {label} OK: 200 with {len(scored)} <= {N_SEED} points "
                      f"(upper-bound semantics, no crash)")
            elif s in (400, 422):
                print(f"leg {label} OK: clean {s} rejection (resource-class norm)")
            else:
                print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on leg [{label}]; no defect conclusion")
                return

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
