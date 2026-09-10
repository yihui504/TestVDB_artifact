#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_recommend_positive_003
# strategy: behavioral positive core — G4 positive-negative pairing anchor
#           for the whole chunk: exercises the documented 200 [ScoredPoint]
#           promise in all THREE documented input variants (by-id example,
#           by-raw-vector example) and closes the documented strategy enum
#           {average_vector, best_score, sum_scores}
# endpoint: points+recommend
# constraint_ids: qdrant_behavioral_points_recommend_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/search/recommend-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-10 (Recommendation Semantics Misunderstanding — the by-id
#            face deliberately EXCLUDES the referenced id itself
#            (exclude_referenced_ids, proven reflection lesson); this
#            script never expects self-inclusion and only RECORDS the
#            exclusion as an observation)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: behavioral positive core x qdrant_behavioral_points_recommend_001 —
  the assertion promises "valid recommend returns HTTP 200 with scored
  points" for the recommend face. Positive closure on a 12-point seeded
  collection (dim 4, Euclid, binary-exact floats — R27), exact=true:
    G    read-back guard: fetch stored vectors of ids 1/2 via the bulk
         points+get face with with_vector=true and verify stored == the
         python-submitted doubles (R27 read-back discipline — the by-vector
         leg uses the READ-BACK vector, never the uploaded raw one)
    P1   by-id: positive=[1], limit=3               -> 200, result array
         1..3 items, EVERY item a ScoredPoint (id + version +
         score:number per contract response_shape); whether id 1 itself
         appears is RECORDED, never asserted (by-id exclusion is
         by-design per the proven reflection lesson)
    P2   by-raw-vector: positive=[readback_vector_of_id_2], limit=3
                                                   -> 200, same shape
    P3a  strategy="average_vector" (documented default, explicit) -> 200
    P3b  strategy="best_score"                      -> 200
    P3c  strategy="sum_scores"                      -> 200
         (enum closure: ALL THREE documented RecommendStrategy values
         accepted; each returns the contract ScoredPoint array shape)
  [chunk_points+recommend coverage (11 scripts): strategy1 limit boundary
  matrix x qdrant_range_points_recommend_001 (limit_001); strategy1 offset
  boundary matrix + huge-offset x qdrant_range_points_recommend_001
  (offset_002); behavioral positive core by-id/by-vector/strategy-enum
  closure x qdrant_behavioral_points_recommend_001 (this script); BS-10
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
Oracle: G -> stored vectors exactly equal the submitted doubles (any
  mismatch = SCRIPT_ERROR: attribution guard, the by-vector leg could not
  be grounded); P1/P2/P3a/P3b/P3c -> each 200 with result a top-level
  ARRAY of 1..3 items, every item carrying id + version + score:number
  (non-200 = Type1_IllegalSuccess per session convention — documented
  valid request rejected; wrong item shape = Type4_StateLogicViolation;
  empty array = Type4, 11 candidates exist so a non-empty result is
  arithmetic-derived; 5xx with /healthz alive = Type3_RuntimeFailure);
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
  points+get (bulk)     -> POST /collections/{collection_name}/points
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
    coll = "bprP3" + tag

    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        vecs = {i: [v * (1.0 + i / 100.0) for v in V] for i in range(1, N_SEED + 1)}
        pts = [{"id": i, "vector": vecs[i]} for i in range(1, N_SEED + 1)]
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": pts}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return

        # ---- Leg G: read-back guard (R27 — read-back baseline, never raw uploads) ----
        s, b, raw = safe_request("POST", f"/collections/{coll}/points",
                                 json={"ids": [1, 2], "with_vector": True,
                                       "with_payload": False}, timeout=60)
        print(f"\nleg G read-back -> status={s}")
        if s != 200 or not isinstance(b, dict) or not isinstance(b.get("result"), list) \
                or len(b["result"]) != 2:
            print(f"raw: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — read-back guard failed, by-vector leg ungrounded")
            return
        by_id_get = {p.get("id"): p.get("vector") for p in b["result"]}
        for pid in (1, 2):
            stored = by_id_get.get(pid)
            if stored != vecs[pid]:
                print(f"read-back mismatch for id {pid}: stored={stored} submitted={vecs[pid]}")
                print("VERDICT: SCRIPT_ERROR — stored vector differs from submitted (R27 guard)")
                return
        print("leg G OK: stored == submitted for ids 1/2 (binary-exact doubles)")

        # ---- Legs P1 / P2 / P3a-c: documented 200 [ScoredPoint] closure ----
        legs = (
            ("P1 by-id positive=[1]", {"positive": [1]}),
            ("P2 by-vector positive=[readback(2)]", {"positive": [vecs[2]]}),
            ("P3a strategy=average_vector", {"positive": [1], "strategy": "average_vector"}),
            ("P3b strategy=best_score", {"positive": [1], "strategy": "best_score"}),
            ("P3c strategy=sum_scores", {"positive": [1], "strategy": "sum_scores"}),
        )
        for label, extra in legs:
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
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: valid "
                          f"recommend returned {s} with service alive: {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return
            scored, shape = extract_scored(b)
            if s != 200 or scored is None:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{label}]: documented "
                      f"valid recommend rejected/malformed with {s} ({shape}): {raw[:300]}")
                return
            if not (1 <= len(scored) <= 3):
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [{label}]: 11 "
                      f"candidates exist and limit=3, so 1..3 points must return, got "
                      f"{len(scored)}: {raw[:300]}")
                return
            for sp in scored:
                if not (isinstance(sp, dict) and "id" in sp and "version" in sp
                        and isinstance(sp.get("score"), (int, float))):
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [{label}]: "
                          f"ScoredPoint must carry id/version/score(number) per contract "
                          f"response_shape: {str(sp)[:200]}")
                    return
            if label.startswith("P1"):
                present = any(sp.get("id") == 1 for sp in scored)
                print(f"  observation: referenced id 1 present in its own result set: {present} "
                      f"(by-id exclusion is documented by-design — recorded, never asserted)")
            print(f"leg {label} OK: 200, {len(scored)} ScoredPoints with contract shape")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
