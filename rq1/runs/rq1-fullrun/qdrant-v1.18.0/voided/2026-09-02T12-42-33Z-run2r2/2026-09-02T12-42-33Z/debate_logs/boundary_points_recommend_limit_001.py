#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_recommend_limit_001
# strategy: strategy1 boundary-value attack on the limit parameter of the
#           recommend face (min-1 + required promise from the range
#           constraint; the vendored v1.18 OpenAPI marks limit the ONLY
#           required field of RecommendRequest)
# endpoint: points+recommend
# constraint_ids: qdrant_range_points_recommend_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/search/recommend-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — clients trust that the
#            documented "limit minimum 1" and "limit required" are actually
#            enforced; a server accepting limit=0/-1, a string limit, or a
#            request with limit omitted breaks pagination arithmetic
#            silently)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary x qdrant_range_points_recommend_001 — the
  contract asserts "limit minimum 1 (required); offset minimum 0" on
  POST /collections/{c}/points/recommend. Boundary matrix on a 12-point
  seeded collection (dim 4, Euclid, binary-exact floats so stored ==
  submitted — R27), by-id positive example with params.exact=true for
  deterministic full-scan ranking:
    L1     limit=1 (min legal closure)        -> 200, EXACTLY 1 ScoredPoint
    L3     limit=3 (above-min closure)        -> 200, EXACTLY 3 ScoredPoints
    L0     limit=0 (min-1 boundary)           -> 400/422 reject
    Lneg   limit=-1 (negative boundary)       -> 400/422 reject
    Lomit  limit omitted (required promise)   -> 400/422 reject (limit is
                                                 the ONLY required field of
                                                 RecommendRequest in the
                                                 vendored v1.18 OpenAPI)
    Ltype  limit="3" (string; strategy2      -> 400/422 reject
           cross-leg)
  Response envelope per contract response_shape: result is a TOP-LEVEL
  ARRAY of ScoredPoint objects ({id, version, score, ...}) — unlike the
  query face where result is an object with a points key; extraction
  asserts that contract shape.
  [chunk_points+recommend coverage (11 scripts): strategy1 limit boundary
  matrix x qdrant_range_points_recommend_001 (this script); strategy1
  offset boundary matrix + huge-offset x qdrant_range_points_recommend_001
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
  qdrant_range_points_recommend_001 (resource_010); strategy7 malformed
  raw-byte stream x qdrant_behavioral_points_recommend_001
  (malformed_011)]
Oracle: L1 -> 200 with EXACTLY 1 ScoredPoint and L3 -> 200 with EXACTLY 3
  (11 candidates exist after by-id example exclusion; count mismatch or a
  non-array result envelope = Type4_StateLogicViolation / shape conflict);
  L0/Lneg/Lomit/Ltype -> 400 or 422 (200 = Type1_IllegalSuccess: min-1 /
  negative / omitted-required / type-confused limit accepted; 5xx with
  /healthz alive = Type3_RuntimeFailure; 404 = misattributed status,
  Type4 mapping violation); transport failure -> /healthz liveness
  re-check then SCRIPT_ERROR (constraint qdrant_range_points_recommend_001).
Constraint: qdrant_range_points_recommend_001 (bare id) — "limit minimum 1
  (required); offset minimum 0" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+recommend      -> POST /collections/{collection_name}/points/recommend
  points+upsert         -> PUT  /collections/{collection_name}/points
  collections+create    -> PUT  /collections/{collection_name}
  collections+delete    -> DELETE /collections/{collection_name}
  healthz               -> GET  /healthz
  (wait is a query parameter on the upsert face — passed via params=;
   consistency/timeout are query parameters of the recommend face — never
   stuffed into the body)
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
# binary-exact floats: stored == submitted under Euclid (no normalization — R27)
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


def extract_scored(body):
    """
    Locate the ScoredPoint array in the recommend envelope.
    Contract response_shape: result (array) -> result[] (object).
    """
    if not isinstance(body, dict):
        return None, "body-not-dict"
    result = body.get("result")
    if isinstance(result, list):
        return result, "result-array"
    return None, "result-missing-or-not-array"


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bprL1" + tag

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

        base = {"positive": [1], "params": {"exact": True}}

        # ---- Leg L1: limit=1 (min legal closure) ----
        s, b, raw = safe_request("POST", f"/collections/{coll}/points/recommend",
                                 json=dict(base, limit=1), timeout=60)
        print(f"\nleg L1 limit=1 -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            alive, _, _ = healthz_alive()
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion" if alive else
                  "VERDICT: SCRIPT_ERROR — transport failure and healthz down")
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [L1 limit=1]: valid "
                      f"recommend returned {s} with service alive: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
            return
        scored, shape = extract_scored(b)
        if s != 200 or scored is None:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [L1 limit=1]: min-closure "
                  f"limit=1 is a documented legal value but got {s} ({shape}): {raw[:300]}")
            return
        if len(scored) != 1:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [L1 limit=1]: limit=1 "
                  f"with 11 candidates must return exactly 1 point, got {len(scored)}: {raw[:300]}")
            return
        sp = scored[0]
        if not (isinstance(sp, dict) and "id" in sp and "version" in sp
                and isinstance(sp.get("score"), (int, float))):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [L1 limit=1]: ScoredPoint "
                  f"shape must carry id/version/score(number) per contract response_shape: {str(sp)[:200]}")
            return
        print("leg L1 OK: exactly 1 ScoredPoint with id/version/score")

        # ---- Leg L3: limit=3 (above-min closure) ----
        s, b, raw = safe_request("POST", f"/collections/{coll}/points/recommend",
                                 json=dict(base, limit=3), timeout=60)
        print(f"\nleg L3 limit=3 -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            alive, _, _ = healthz_alive()
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion" if alive else
                  "VERDICT: SCRIPT_ERROR — transport failure and healthz down")
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [L3 limit=3]: valid "
                      f"recommend returned {s} with service alive: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
            return
        scored, shape = extract_scored(b)
        if s != 200 or scored is None:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [L3 limit=3]: legal "
                  f"limit=3 rejected/malformed with {s} ({shape}): {raw[:300]}")
            return
        if len(scored) != 3:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [L3 limit=3]: limit=3 "
                  f"with 11 candidates must return exactly 3 points, got {len(scored)}: {raw[:300]}")
            return
        print("leg L3 OK: exactly 3 ScoredPoints")

        # ---- Negative legs: L0 / Lneg / Lomit / Ltype -> must be rejected ----
        neg_legs = (
            ("L0 limit=0", dict(base, limit=0)),
            ("Lneg limit=-1", dict(base, limit=-1)),
            ("Lomit limit-omitted", dict(base)),
            ("Ltype limit='3'", dict(base, limit="3")),
        )
        for label, payload in neg_legs:
            s, b, raw = safe_request("POST", f"/collections/{coll}/points/recommend",
                                     json=payload, timeout=60)
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
                          f"limit returned {s} (must be a clean 4xx) with service alive: {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return
            if s == 200:
                n = len(extract_scored(b)[0] or [])
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{label}]: contract "
                      f"asserts limit minimum 1 (required), but the request was ACCEPTED with 200 "
                      f"({n} points returned): {raw[:300]}")
                return
            if s == 404:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [{label}]: 404 is "
                      f"the documented status for a MISSING COLLECTION; the collection exists, got "
                      f"404 for an illegal limit: {raw[:300]}")
                return
            if s not in (400, 422):
                print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on leg [{label}]; no defect conclusion")
                return
            # Type2 observation only (R29: error-naming carries no verdict weight)
            named = "limit" in raw.lower()
            print(f"leg {label} OK: rejected with {s} (error names 'limit': {named})")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
