#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_recommend_using_mismatch_005
# strategy: behavioral negative — the "fetched vectors must match the
#           using-vector characteristics" clause: referenced points that
#           exist but whose vectors do not match the used vector space
#           (lookup_from cross-collection dimension mismatch) or that lack
#           the used named vector (partial named-vector point) must map
#           to the documented 400, never to a 200 computed from
#           mismatched vectors
# endpoint: points+recommend
# constraint_ids: qdrant_behavioral_points_recommend_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/search/recommend-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — clients trust that the
#            characteristics check runs BEFORE any vector arithmetic; a
#            200 from a dim-6 example in a dim-4 space would mean the
#            check was skipped and undefined vector math executed)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: behavioral characteristics-mismatch x qdrant_behavioral_points_
  recommend_001 — the assertion promises "400 when a positive/negative
  references a point WITHOUT THE USED VECTOR ... (fetched vectors must
  match the using-vector characteristics)". Two construction families:
    FAMILY A (lookup_from dimension mismatch):
      main   collection dim 4 (unnamed), ids 1..12
      lookup4 collection dim 4 (unnamed), ids 1..12 — compatible control
      lookup6 collection dim 6 (unnamed), ids 1..12 — mismatch
      A1 guard: lookup_from=lookup4, positive=[1]  -> 200 non-empty
                (lookup path live; the later 400 attributes to the
                dimension mismatch, not to lookup_from breakage)
      A2 leg:   lookup_from=lookup6,  positive=[1]  -> 400/422 (fetched
                dim-6 vector cannot serve a dim-4 space; the vendored
                lookup_from description itself says the other collection
                "should have the same vector size as the current
                collection")
    FAMILY B (named-vector partial point):
      named collection vectors {txt: dim4, img: dim4}; point 201 carries
      ONLY txt (partial named-vector upsert), point 202 carries both
      B1 guard: using="txt", positive=[201]         -> 200 non-empty
      B2 leg:   using="img", positive=[201]         -> 400/422 (point
                exists but HAS no img vector — the exact "without the
                used vector" phrase)
      B3 leg:   using="img", positive=[202],
                negative=[201]                      -> 400/422 (a missing
                NEGATIVE example vector fails the same way)
      (if the server rejects the partial named-vector upsert itself — no
      in-chunk promise either way — B legs are SKIPPED with a note and
      only FAMILY A adjudicates)
  [chunk_points+recommend coverage (11 scripts): strategy1 limit boundary
  matrix x qdrant_range_points_recommend_001 (limit_001); strategy1 offset
  boundary matrix + huge-offset x qdrant_range_points_recommend_001
  (offset_002); behavioral positive core by-id/by-vector/strategy-enum
  closure x qdrant_behavioral_points_recommend_001 (positive_003); BS-10
  missing referenced point ids 400-legs x qdrant_behavioral_points_
  recommend_001 (missing_ref_004); using-vector characteristics mismatch
  (lookup dim + named partial) x qdrant_behavioral_points_recommend_001
  (this script); 404 status-mapping legs x qdrant_behavioral_
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
Oracle: A1/B1 -> 200 with a non-empty ScoredPoint array (non-200 =
  SCRIPT_ERROR attribution failure, no defect conclusion from the paired
  leg); A2/B2/B3 -> 400 or 422 clean rejection (200 = Type1_IllegalSuccess:
  the request was computed from vectors that do not match the used vector
  space — count recorded; 404 = Type4_StateLogicViolation misattributed
  status, all collections exist; 5xx with /healthz alive =
  Type3_RuntimeFailure); transport failure -> /healthz liveness re-check
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
DIM6 = 6
N_SEED = 12
V = [0.5, 0.25, 0.125, 0.0625]
V6 = [0.5, 0.25, 0.125, 0.0625, 0.03125, 0.015625]


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


def adjudicate_reject(label, s, b, raw, context):
    """Shared 4xx adjudication for the mismatch legs (declare-then-compare)."""
    if s == -1:
        alive, _, _ = healthz_alive()
        print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion" if alive else
              "VERDICT: SCRIPT_ERROR — transport failure and healthz down")
        return False
    if 500 <= s <= 599:
        alive, _, _ = healthz_alive()
        if alive:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: "
                  f"{context} produced {s} (must be a clean 4xx) with service alive: {raw[:300]}")
        else:
            print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
        return False
    if s == 200:
        n = len(extract_scored(b)[0] or [])
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{label}]: {context}; the "
              f"request was ACCEPTED with 200 ({n} points returned from mismatched vectors): "
              f"{raw[:300]}")
        return False
    if s == 404:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [{label}]: {context}; 404 "
              f"is the documented status of a MISSING COLLECTION but all collections exist: "
              f"{raw[:300]}")
        return False
    if s not in (400, 422):
        print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on leg [{label}]; no defect conclusion")
        return False
    print(f"leg {label} OK: rejected with {s} (context: {context})")
    return True


def main():
    tag = uuid.uuid4().hex[:8]
    main_c = "bprU5a" + tag
    lookup4 = "bprU5b" + tag
    lookup6 = "bprU5c" + tag
    named = "bprU5d" + tag
    created = []

    def make_coll(name, vectors_cfg, points):
        s, _, raw = safe_request("PUT", f"/collections/{name}",
                                 json={"vectors": vectors_cfg}, timeout=60)
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
        if not make_coll(main_c, {"size": DIM, "distance": "Euclid"},
                         [{"id": i, "vector": [v * (1.0 + i / 100.0) for v in V]}
                          for i in range(1, N_SEED + 1)]):
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return
        if not make_coll(lookup4, {"size": DIM, "distance": "Euclid"},
                         [{"id": i, "vector": [v * (1.0 + i / 100.0) for v in V]}
                          for i in range(1, N_SEED + 1)]):
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return
        if not make_coll(lookup6, {"size": DIM6, "distance": "Euclid"},
                         [{"id": i, "vector": [v * (1.0 + i / 100.0) for v in V6]}
                          for i in range(1, N_SEED + 1)]):
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return

        # ---- Leg A1: guard — compatible dim-4 lookup works ----
        s, b, raw = safe_request("POST", f"/collections/{main_c}/points/recommend",
                                 json={"positive": [1], "limit": 3, "params": {"exact": True},
                                       "lookup_from": {"collection": lookup4}}, timeout=60)
        print(f"\nleg A1 lookup_from dim-4 (guard) -> status={s}")
        print(f"raw: {raw[:400]}")
        scored, shape = extract_scored(b)
        if s != 200 or scored is None or len(scored) < 1:
            if s == -1 or 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                print("VERDICT: SCRIPT_ERROR — guard transport/5xx, no defect conclusion" if alive
                      else "VERDICT: SCRIPT_ERROR — guard failed and healthz down")
            else:
                print(f"VERDICT: SCRIPT_ERROR — compatible-lookup guard failed ({s}, {shape}); "
                      f"A2 unattributable")
            return
        print("leg A1 OK: dim-4 lookup live")

        # ---- Leg A2: dim-6 lookup -> characteristics mismatch -> 400 ----
        s, b, raw = safe_request("POST", f"/collections/{main_c}/points/recommend",
                                 json={"positive": [1], "limit": 3, "params": {"exact": True},
                                       "lookup_from": {"collection": lookup6}}, timeout=60)
        print(f"\nleg A2 lookup_from dim-6 -> status={s}")
        print(f"raw: {raw[:400]}")
        if not adjudicate_reject("A2 lookup dim-6", s, b, raw,
                                 "fetched dim-6 example vectors cannot serve the dim-4 space"):
            return

        # ---- FAMILY B: named-vector partial point ----
        partial_ok = make_coll(
            named,
            {"txt": {"size": DIM, "distance": "Euclid"},
             "img": {"size": DIM, "distance": "Euclid"}},
            [{"id": 201, "vector": {"txt": [v * 1.02 for v in V]}},
             {"id": 202, "vector": {"txt": [v * 1.03 for v in V],
                                    "img": [-v * 1.03 for v in V]}}],
        )
        if not partial_ok:
            print("\nNOTE: partial named-vector upsert rejected by the server — no in-chunk "
                  "promise either way; FAMILY B legs SKIPPED, FAMILY A already adjudicated")
            print("VERDICT: NO_DEFECT")
            return

        # B1 guard: using=txt on the txt-only point works
        s, b, raw = safe_request("POST", f"/collections/{named}/points/recommend",
                                 json={"positive": [201], "limit": 3, "params": {"exact": True},
                                       "using": "txt"}, timeout=60)
        print(f"\nleg B1 using=txt on partial point (guard) -> status={s}")
        print(f"raw: {raw[:400]}")
        scored, shape = extract_scored(b)
        if s != 200 or scored is None or len(scored) < 1:
            if s == -1 or 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                print("VERDICT: SCRIPT_ERROR — guard transport/5xx, no defect conclusion" if alive
                      else "VERDICT: SCRIPT_ERROR — guard failed and healthz down")
            else:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [B1]: point 201 HAS "
                      f"the txt vector and the documented request must succeed, got {s} "
                      f"({shape}): {raw[:300]}")
            return
        print("leg B1 OK: txt face of the partial point live")

        # B2: using=img on the point WITHOUT img -> 400
        s, b, raw = safe_request("POST", f"/collections/{named}/points/recommend",
                                 json={"positive": [201], "limit": 3, "params": {"exact": True},
                                       "using": "img"}, timeout=60)
        print(f"\nleg B2 using=img on txt-only point -> status={s}")
        print(f"raw: {raw[:400]}")
        if not adjudicate_reject("B2 using=img, point lacks img", s, b, raw,
                                 "point 201 exists but has no img vector (the exact 'without "
                                 "the used vector' clause)"):
            return

        # B3: negative reference lacking the used vector -> 400
        s, b, raw = safe_request("POST", f"/collections/{named}/points/recommend",
                                 json={"positive": [202], "negative": [201], "limit": 3,
                                       "params": {"exact": True}, "using": "img"}, timeout=60)
        print(f"\nleg B3 negative ref lacks img -> status={s}")
        print(f"raw: {raw[:400]}")
        if not adjudicate_reject("B3 negative without used vector", s, b, raw,
                                 "negative example 201 has no img vector"):
            return

        print("VERDICT: NO_DEFECT")
    finally:
        for name in (named, lookup6, lookup4, main_c):
            try:
                safe_request("DELETE", f"/collections/{name}", timeout=60)
            except Exception:
                pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
