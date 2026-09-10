#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_recommend_404_006
# strategy: behavioral negative — the documented 404 mapping for a MISSING
#           COLLECTION on the recommend face (exact-status adjudication:
#           404 is the promise, not a generic 4xx), plus the missing
#           lookup_from-collection face as an observation leg
# endpoint: points+recommend
# constraint_ids: qdrant_behavioral_points_recommend_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/search/recommend-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — clients branch error
#            handling on 404=collection-missing vs 400=request-invalid;
#            a 2xx here would mean a recommend answered against a
#            nonexistent collection)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: behavioral 404-mapping x qdrant_behavioral_points_recommend_001 —
  the assertion promises "404 for a missing collection" on the recommend
  face. Legs (the referenced id is deliberately seeded in a REAL sibling
  collection so nothing but the collection name is wrong):
    G    guard: the SAME request against an EXISTING collection -> 200
         non-empty (proves body validity; every 4xx on the N-legs then
         attributes to the missing collection name)
    N1   valid body, missing collection        -> 404 EXACTLY
    N2   invalid body (limit=0) + missing      -> still a 4xx (which
         collection                                 status wins is
                                                  recorded; a 200 would
                                                  be a Type1)
    N3   existing collection but lookup_from   -> 4xx expected (no valid
         points at a MISSING collection              examples can be
                                                  fetched from nowhere;
                                                  recorded for the judge —
                                                  2xx = Type1 candidate)
  [chunk_points+recommend coverage (11 scripts): strategy1 limit boundary
  matrix x qdrant_range_points_recommend_001 (limit_001); strategy1 offset
  boundary matrix + huge-offset x qdrant_range_points_recommend_001
  (offset_002); behavioral positive core by-id/by-vector/strategy-enum
  closure x qdrant_behavioral_points_recommend_001 (positive_003); BS-10
  missing referenced point ids 400-legs x qdrant_behavioral_points_
  recommend_001 (missing_ref_004); using-vector characteristics mismatch
  (lookup dim + named partial) x qdrant_behavioral_points_recommend_001
  (using_mismatch_005); 404 status-mapping legs x qdrant_behavioral_
  points_recommend_001 (this script); strategy2 RecommendExample oneOf
  element type-confusion + raw-vector dimension x qdrant_behavioral_
  points_recommend_001 (example_type_007); R33/R40 dual-key silent-drop
  family on mixed recommend examples x qdrant_behavioral_points_
  recommend_001 (dualkey_008); strategy2 filter type-confusion family
  mirror x qdrant_behavioral_points_recommend_001 (filter_type_009);
  strategy6 conservative single-extreme + modest-product resource x
  qdrant_range_points_recommend_001 (resource_010); strategy7 malformed
  raw-byte stream x qdrant_behavioral_points_recommend_001
  (malformed_011)]
Oracle: G -> 200 with a non-empty ScoredPoint array (non-200 = SCRIPT_ERROR
  attribution failure); N1 -> 404 EXACTLY (2xx = Type1_IllegalSuccess:
  recommend answered against a nonexistent collection; 400/422 =
  Type4_StateLogicViolation: the documented 404-for-missing-collection
  mapping violated; 5xx with /healthz alive = Type3_RuntimeFailure); N2 ->
  any 4xx (200 = Type1); N3 -> 4xx (200 = Type1 candidate pending judge:
  no valid examples can be fetched from a nonexistent lookup collection);
  transport failure -> /healthz liveness re-check then SCRIPT_ERROR
  (constraint qdrant_behavioral_points_recommend_001).
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
    coll = "bprN6" + tag
    ghost = "bprN6ghost" + tag
    ghost_lookup = "bprN6lookup" + tag

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

        good_body = {"positive": [1], "limit": 3, "params": {"exact": True}}

        # ---- Leg G: guard — same body against the existing collection ----
        s, b, raw = safe_request("POST", f"/collections/{coll}/points/recommend",
                                 json=good_body, timeout=60)
        print(f"\nleg G existing collection (guard) -> status={s}")
        print(f"raw: {raw[:400]}")
        scored, shape = extract_scored(b)
        if s != 200 or scored is None or len(scored) < 1:
            if s == -1 or 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                print("VERDICT: SCRIPT_ERROR — guard transport/5xx, no defect conclusion" if alive
                      else "VERDICT: SCRIPT_ERROR — guard failed and healthz down")
            else:
                print(f"VERDICT: SCRIPT_ERROR — guard failed ({s}, {shape}); N-legs unattributable")
            return
        print("leg G OK: body is valid against a live collection")

        # ---- Leg N1: missing collection, valid body -> 404 exactly ----
        s, b, raw = safe_request("POST", f"/collections/{ghost}/points/recommend",
                                 json=good_body, timeout=60)
        print(f"\nleg N1 missing collection -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            alive, _, _ = healthz_alive()
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion" if alive else
                  "VERDICT: SCRIPT_ERROR — transport failure and healthz down")
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [N1]: missing "
                      f"collection produced {s} with service alive: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
            return
        if s == 200:
            n = len(extract_scored(b)[0] or [])
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [N1]: recommend on a "
                  f"NONEXISTENT collection answered 200 ({n} points): {raw[:300]}")
            return
        if s != 404:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [N1]: the documented "
                  f"status for a missing collection is 404, got {s}: {raw[:300]}")
            return
        print("leg N1 OK: 404 exactly as documented")

        # ---- Leg N2: missing collection + invalid limit -> any 4xx ----
        s, b, raw = safe_request("POST", f"/collections/{ghost}/points/recommend",
                                 json={"positive": [1], "limit": 0}, timeout=60)
        print(f"\nleg N2 missing collection + limit=0 -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            alive, _, _ = healthz_alive()
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion" if alive else
                  "VERDICT: SCRIPT_ERROR — transport failure and healthz down")
            return
        if s == 200:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [N2]: nonexistent "
                  f"collection + illegal limit=0 answered 200: {raw[:300]}")
            return
        if not (400 <= s <= 499):
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [N2]: got {s} with "
                      f"service alive: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
            return
        print(f"leg N2 OK: 4xx ({s}) — precedence recorded for the judge")

        # ---- Leg N3: existing collection, lookup_from points at a MISSING collection ----
        s, b, raw = safe_request("POST", f"/collections/{coll}/points/recommend",
                                 json=dict(good_body, lookup_from={"collection": ghost_lookup}),
                                 timeout=60)
        print(f"\nleg N3 lookup_from missing collection -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            alive, _, _ = healthz_alive()
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion" if alive else
                  "VERDICT: SCRIPT_ERROR — transport failure and healthz down")
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [N3]: missing lookup "
                      f"collection produced {s} with service alive: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
            return
        if s == 200:
            n = len(extract_scored(b)[0] or [])
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [N3]: no valid examples "
                  f"can be fetched from a NONEXISTENT lookup collection, yet 200 with {n} "
                  f"points: {raw[:300]}")
            return
        if not (400 <= s <= 499):
            print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on leg [N3]; no defect conclusion")
            return
        print(f"leg N3 OK: 4xx ({s}) — exact status recorded for the judge")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
