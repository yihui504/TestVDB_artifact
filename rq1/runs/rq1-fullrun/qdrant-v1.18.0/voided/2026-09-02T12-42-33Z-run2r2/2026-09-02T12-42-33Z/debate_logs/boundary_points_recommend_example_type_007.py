#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_recommend_example_type_007
# strategy: strategy2 type-boundary attack on the RecommendExample untagged
#           oneOf (positive[] elements are oneOf {PointId(uint64|uuid),
#           dense vector, SparseVector} per the vendored v1.18 OpenAPI) —
#           type-confused elements and raw-vector dimension faces
# endpoint: points+recommend
# constraint_ids: qdrant_behavioral_points_recommend_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/search/recommend-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — the untagged oneOf is
#            resolved per element; clients trust serde rejects elements
#            matching NO variant and raw vectors with the wrong dimension;
#            a silent 200 means an arbitrary JSON value flowed into vector
#            math — the same trust family the R33/R40 dual-key instances
#            proved on other faces)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type x qdrant_behavioral_points_recommend_001 — the
  positive[] elements are RecommendExample = oneOf {ExtendedPointId
  (uint64 | uuid string), dense vector [double], SparseVector {indices,
  values}} (untagged per the vendored v1.18 OpenAPI; the same serde family
  the R33/R40 dual-key instances proved permissive on sibling faces).
  Live guards first (G4 pairing), then type-confusion and dimension faces
  on a 12-point dim-4 Euclid collection (binary-exact — R27):
    G1   guard: positive=[1] (id variant)          -> 200 non-empty
    G2   guard: positive=[[readback(2)]] (vector   -> 200 non-empty
         variant; the read-back stored vector is used, never the raw
         upload — R27)
    T1   positive="1"  (array field as STRING)     -> 400/422
    T2   positive=[true] (bool element: no variant)-> 400/422
    T3   positive=[{"id": 5}] (object with an id   -> 400/422 (the ONLY
         key — no oneOf variant is an id-object;  SparseVector variant
         a client-invented wrapper shape)              requires indices+
                                                       values; 200 = oneOf
                                                       resolution accepted
                                                       an unlicensed shape)
    T4   positive=[[]] (EMPTY dense vector, 0      -> 400/422 (dimension
         dims vs 4)                                      face: no vector
                                                       variant matches a
                                                       dim-4 space)
    T5   positive=[[0.5, 0.25, 0.125]] (3 dims     -> 400/422 (raw-vector
         vs 4 — strategy3 dimension face)               dimension mismatch
                                                       vs the dim-4 space)
    T6   positive=[-1] (negative integer id —      -> 400/422 (uint64
         uint64 variant must reject)                     variant violated)
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
  recommend_001 (this script); R33/R40 dual-key silent-drop family on
  mixed recommend examples x qdrant_behavioral_points_recommend_001
  (dualkey_008); strategy2 filter type-confusion family mirror x
  qdrant_behavioral_points_recommend_001 (filter_type_009); strategy6
  conservative single-extreme + modest-product resource x
  qdrant_range_points_recommend_001 (resource_010); strategy7 malformed
  raw-byte stream x qdrant_behavioral_points_recommend_001
  (malformed_011)]
Oracle: G1/G2 -> 200 with a non-empty ScoredPoint array each (non-200 =
  SCRIPT_ERROR attribution failure — both documented oneOf variants must
  be live before any 4xx is trusted); T1..T6 -> 400 or 422 clean rejection
  (200 = Type1_IllegalSuccess: an element matching NO oneOf variant (or a
  wrong-dimension raw vector) was accepted into the recommend pipeline —
  returned count/ids recorded as the winning-variant fingerprint for the
  judge; 5xx with /healthz alive = Type3_RuntimeFailure); transport
  failure -> /healthz liveness re-check then SCRIPT_ERROR
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
    coll = "bprT7" + tag

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

        # read-back guard for the G2 vector example (R27)
        s, b, raw = safe_request("POST", f"/collections/{coll}/points",
                                 json={"ids": [2], "with_vector": True,
                                       "with_payload": False}, timeout=60)
        if s != 200 or not isinstance(b, dict) or not isinstance(b.get("result"), list) \
                or len(b["result"]) != 1 or b["result"][0].get("vector") != vecs[2]:
            print(f"read-back guard failed: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — read-back mismatch, vector-variant guard ungrounded")
            return
        print("read-back guard OK: stored vector of id 2 == submitted (R27)")

        def run(label, positive_val, body_level_string=False):
            payload = {"limit": 3, "params": {"exact": True}}
            if body_level_string:
                payload["positive"] = positive_val
            else:
                payload["positive"] = positive_val
            return safe_request("POST", f"/collections/{coll}/points/recommend",
                                json=payload, timeout=60)

        # ---- Guards G1 / G2: both documented oneOf variants live ----
        for label, pos in (("G1 positive=[1] (id variant)", [1]),
                           ("G2 positive=[[readback(2)]] (vector variant)", [vecs[2]])):
            s, b, raw = run(label, pos)
            print(f"\nleg {label} -> status={s}")
            print(f"raw: {raw[:400]}")
            if s == -1 or 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if s == -1:
                    print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion" if alive
                          else "VERDICT: SCRIPT_ERROR — transport failure and healthz down")
                elif alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: {s} "
                          f"with service alive: {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return
            scored, shape = extract_scored(b)
            if s != 200 or scored is None or len(scored) < 1:
                print(f"VERDICT: SCRIPT_ERROR — guard [{label}] failed ({s}, {shape}); "
                      f"T-legs unattributable")
                return
            print(f"leg {label} OK: variant live")

        # ---- T1..T6: type-confused / dimension-mismatch elements ----
        t_legs = (
            ("T1 positive='1' (array as string)", "1"),
            ("T2 positive=[true]", [True]),
            ("T3 positive=[{'id': 5}] (unlicensed object)", [{"id": 5}]),
            ("T4 positive=[[]] (0-dim vector)", [[]]),
            ("T5 positive=[[0.5,0.25,0.125]] (3-dim vs 4)", [[0.5, 0.25, 0.125]]),
            ("T6 positive=[-1] (negative uint id)", [-1]),
        )
        for label, pos in t_legs:
            s, b, raw = run(label, pos)
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
                          f"type-confused element produced {s} (must be a clean 4xx) with "
                          f"service alive: {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return
            if s == 200:
                scored, shape = extract_scored(b)
                n = len(scored) if scored is not None else -1
                ids = [sp.get("id") for sp in scored][:5] if scored else None
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{label}]: an element "
                      f"matching NO oneOf variant (or a wrong-dimension vector) was ACCEPTED "
                      f"with 200 ({n} points, ids {ids} recorded as the winning-variant "
                      f"fingerprint): {raw[:300]}")
                return
            if s not in (400, 422):
                print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on leg [{label}]; no defect conclusion")
                return
            print(f"leg {label} OK: rejected with {s}")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
