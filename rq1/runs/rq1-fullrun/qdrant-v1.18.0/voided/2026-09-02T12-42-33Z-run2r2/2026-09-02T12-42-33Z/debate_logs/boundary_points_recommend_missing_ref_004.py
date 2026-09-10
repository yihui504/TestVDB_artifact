#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_recommend_missing_ref_004
# strategy: behavioral negative — the documented 400 mapping when a
#           positive/negative example references a MISSING point (BS-10
#           face from the TMA recommended order: "missing positive point
#           IDs, missing negative point IDs"), with a live valid-by-id
#           guard so the 400s attribute to the missing reference and not
#           to general by-id breakage (G4 pairing)
# endpoint: points+recommend
# constraint_ids: qdrant_behavioral_points_recommend_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/search/recommend-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-10 (Recommendation Semantics Misunderstanding — clients
#            assume missing referenced ids surface as a clean per-request
#            400; a 200-with-empty-result or a 404 misattribution silently
#            changes error handling)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: behavioral 400-leg x qdrant_behavioral_points_recommend_001 — the
  assertion promises "400 when a positive/negative references ... a missing
  point". Matrix on a 12-point seeded collection (dim 4, Euclid,
  binary-exact — R27):
    G    guard: valid by-id positive=[1]        -> 200 (proves the by-id
         lookup path live; a later 400 attributes to the missing id)
    M1   positive=[999999] (missing id)         -> 400/422
    M2   negative=[999999] (missing id)         -> 400/422
    M3   positive=[1] + negative=[999999]       -> 400/422 (a missing
         negative reference must fail the request the same way)
    M4   positive=[999999, 888888] (all missing)-> 400/422
    M5   positive=[1, 999999] (mixed live+dead) -> 400/422 (ONE missing
         example poisons the whole request per the any-example phrasing)
  Status-mapping adjudication: the documented status for a missing
  referenced point is 400; 404 is the documented status of a MISSING
  COLLECTION (this collection exists), so a 404 here misattributes the
  failure; 2xx silently returns a result computed from examples that were
  never fetched.
  [chunk_points+recommend coverage (11 scripts): strategy1 limit boundary
  matrix x qdrant_range_points_recommend_001 (limit_001); strategy1 offset
  boundary matrix + huge-offset x qdrant_range_points_recommend_001
  (offset_002); behavioral positive core by-id/by-vector/strategy-enum
  closure x qdrant_behavioral_points_recommend_001 (positive_003); BS-10
  missing referenced point ids 400-legs x qdrant_behavioral_points_
  recommend_001 (this script); using-vector characteristics mismatch
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
Oracle: G -> 200 with a non-empty ScoredPoint array (non-200 = SCRIPT_ERROR
  attribution failure — the by-id path is broken for a reason unrelated to
  the missing-reference legs, no defect conclusion from M-legs); M1..M5 ->
  400 or 422 clean rejection (200 = Type1_IllegalSuccess: recommend
  computed from references that were never fetched, count recorded; 404 =
  Type4_StateLogicViolation status-mapping: missing point misreported as
  missing collection while the collection exists; 5xx with /healthz alive
  = Type3_RuntimeFailure); transport failure -> /healthz liveness re-check
  then SCRIPT_ERROR (constraint qdrant_behavioral_points_recommend_001).
Constraint: qdrant_behavioral_points_recommend_001 (bare id) — "returns
  200 [ScoredPoint]; 400 when a positive/negative references a point
  without the used vector or a missing point (fetched vectors must match
  the using-vector characteristics); 404 for a missing collection"
  (evidence_tier: explicit; level: endpoint)

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
    coll = "bprM4" + tag

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

        # ---- Leg G: live guard — valid by-id recommend works ----
        s, b, raw = safe_request("POST", f"/collections/{coll}/points/recommend",
                                 json={"positive": [1], "limit": 3, "params": {"exact": True}},
                                 timeout=60)
        print(f"\nleg G valid by-id -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            alive, _, _ = healthz_alive()
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion" if alive else
                  "VERDICT: SCRIPT_ERROR — transport failure and healthz down")
            return
        scored, shape = extract_scored(b)
        if s != 200 or scored is None or len(scored) < 1:
            print(f"VERDICT: SCRIPT_ERROR — by-id guard failed ({s}, {shape}); M-legs unattributable")
            return
        print("leg G OK: by-id path live — later 400s attribute to the missing references")

        # ---- Legs M1..M5: missing referenced point -> documented 400 ----
        m_legs = (
            ("M1 positive=[999999]", {"positive": [999999]}),
            ("M2 negative=[999999]", {"negative": [999999]}),
            ("M3 positive=[1] negative=[999999]", {"positive": [1], "negative": [999999]}),
            ("M4 positive=[999999, 888888]", {"positive": [999999, 888888]}),
            ("M5 positive=[1, 999999]", {"positive": [1, 999999]}),
        )
        for label, extra in m_legs:
            payload = dict(extra)
            payload.update({"limit": 3, "params": {"exact": True}})
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
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: missing "
                          f"reference produced {s} (must be a clean 4xx) with service alive: "
                          f"{raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return
            if s == 200:
                n = len(extract_scored(b)[0] or [])
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{label}]: contract "
                      f"promises 400 for a missing referenced point, but the request was ACCEPTED "
                      f"with 200 ({n} points returned from never-fetched references): {raw[:300]}")
                return
            if s == 404:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [{label}]: 404 is "
                      f"the documented status of a MISSING COLLECTION, but this collection exists; "
                      f"a missing referenced POINT must map to 400: {raw[:300]}")
                return
            if s not in (400, 422):
                print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on leg [{label}]; no defect conclusion")
                return
            named = ("999999" in raw) or ("point" in raw.lower())
            print(f"leg {label} OK: rejected with {s} (error references the missing point: {named})")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
