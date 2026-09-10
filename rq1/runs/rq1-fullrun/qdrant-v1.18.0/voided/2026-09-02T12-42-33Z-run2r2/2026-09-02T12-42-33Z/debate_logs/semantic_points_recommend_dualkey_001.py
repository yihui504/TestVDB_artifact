#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_recommend_dualkey_001
# strategy: strategy6 metamorphic (by-id == by-stored-vector) + dual-key
#           family exploration on the RecommendExample untagged oneOf
# endpoint: points+recommend
# constraint_ids: qdrant_behavioral_points_recommend_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/search/recommend-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (type coercion in nested untagged oneOf structures)
# exploration_target: M1-M3 = regression | D1/D2/D4/D5 = novel_candidate
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy6 metamorphic + dual-key x qdrant_behavioral_points_recommend_001 —
  the versioned spec types positive/negative as array[RecommendExample]
  with RecommendExample an UNTAGGED oneOf [uint64|uuid PointId |
  array<double> dense vector | SparseVector{indices,values}]. Reflection
  context: the serde untagged-oneOf silent-drop family is 3x CONFIRMED on
  query faces; the recommend example variants are the unmeasured face of
  the same family. Metamorphic core (dim-4 Euclid, x-axis, exact=true;
  universe: 301 at x=10.0, candidates 303..308 strictly left):
    M1 positive=[301] (by id)        -> R1: 200, 6 ranked ids, 301
       itself EXCLUDED (by-design referenced-id exclusion — live-measure
       lesson; never expect self)
    M2 positive=[[10,0,0,0]] (raw)   -> R2: 200; the by-id path fetches
       exactly this stored vector, so R2 minus {301} must EQUAL R1
    M3 positive=[301, [10,0,0,0]]    -> 200 (spec-legal MIXED variant
       array; avg of identical vectors = the same query; referenced id
       still excluded) and R3 == R1; a 4xx here = legal mixed oneOf
       array wrongly rejected
  Dual-key / no-variant novel faces (each must be REJECTED, silent
  acceptance = the confirmed drop family):
    D1 positive=[{"bogus": 1}]       -> object matching NO variant
    D2 positive=[{"indices": [0,1]}] -> SparseVector with required
       'values' missing (half-keyed variant)
    D4 positive=["301"]              -> non-uuid digit string (neither
       uint64 nor uuid PointId)
    D5 {} (positive absent entirely) -> the contract's api_endpoints
       table marks positive required:true (OpenAPI shard says required:
       [limit] only — conflict recorded; the contract table is the
       adjudication source, D3b spec-vs-table recorded both ways)
    D3 positive=[{"indices":[0,1],"values":[0.1,0.2]}] (well-formed
       SparseVector against a DENSE unnamed vector) -> disposition
       NOTE only (characteristics wording covers fetched vectors, not
       raw examples — not adjudicated)
  [chunk_points+recommend semantic coverage — see
   semantic_points_recommend_behavior_001 docstring for the full 7-script
   list; this script = 007 metamorphic + dual-key x behavioral_001]
Oracle: M1 -> 200 with 6 ids excluding 301; M2 -> 200 and [ids != 301]
  == R1 ids in the same order (metamorphic relation broken =
  Type4_StateLogicViolation; 4xx on M2 = Type1_IllegalRejection); M3 ->
  200 with ids == R1 (4xx = Type1_IllegalRejection of a spec-legal mixed
  array; 200 with different ids = Type4); D1/D2/D4/D5 -> 400-family 4xx,
  any 2xx = Type1_IllegalSuccess (an element matching no oneOf variant —
  or no example at all — silently dropped/coerced); 5xx with /healthz
  alive = Type3_RuntimeFailure; transport failure -> /healthz re-check
  then SCRIPT_ERROR (constraint qdrant_behavioral_points_recommend_001).
Constraint: qdrant_behavioral_points_recommend_001 — "valid recommend
  returns HTTP 200 with scored points; 400 when a positive/negative
  references a point without the used vector or a missing point"
  (evidence_tier: explicit; level: endpoint) + endpoint spec
  array[PointId|vector] example typing

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+recommend       -> POST /collections/{collection_name}/points/recommend
  points+upsert          -> PUT  /collections/{collection_name}/points
  collections+create     -> PUT  /collections/{collection_name}
  collections+delete     -> DELETE /collections/{collection_name}
  healthz                -> GET  /healthz
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

POS_ID = 301
POS_VEC = [10.0, 0.0, 0.0, 0.0]
SEED = [{"id": POS_ID, "vector": POS_VEC}] + [
    {"id": pid, "vector": [x, 0.0, 0.0, 0.0]}
    for pid, x in ((303, 9.3), (304, 9.0), (305, 8.0), (306, 6.0), (307, 3.0), (308, 0.0))
]


def safe_request(method, endpoint, json=None, timeout=60, params=None):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text); transport failure -> (-1, err, err).
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
    hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
    return hs == 200, hs, str(hraw)[:200]


def transport_dead(where):
    alive, hs, hraw = healthz_alive()
    print(f"transport failure on {where} (healthz status={hs}: {hraw})")
    print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")


def handle_5xx(rs, rraw, leg):
    if not (500 <= rs <= 599):
        return False
    alive, _, _ = healthz_alive()
    if alive:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{leg}]: {rs} "
              f"with service alive: {rraw[:300]}")
    else:
        print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
    return True


def get_results(body):
    if isinstance(body, dict):
        r = body.get("result")
        if isinstance(r, list):
            return r
    return None


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "srmm" + tag

    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": SEED}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return
        rpath = f"/collections/{coll}/points/recommend"

        def run(leg, body):
            st, bd, rw = safe_request("POST", rpath, json=body, timeout=60)
            print(f"{leg} -> status={st}")
            print(f"raw: {rw[:400]}")
            if st == -1:
                transport_dead(leg)
                return None
            if handle_5xx(st, rw, leg):
                return None
            return st, get_results(bd), rw

        # ---- M1: by-id (regression baseline; 301 excluded by design) ----
        r1 = run("M1 positive=[301] (by id)",
                 {"positive": [POS_ID], "limit": 6, "params": {"exact": True}})
        if r1 is None:
            return
        st1, res1, rw1 = r1
        if st1 != 200 or res1 is None or len(res1) != 6:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) — M1: valid "
                  f"by-id recommend must return 200 with the 6 non-referenced "
                  f"points (301 excluded by design), got status={st1}, "
                  f"len={None if res1 is None else len(res1)}: {rw1[:250]}")
            return
        ids1 = [p.get("id") for p in res1]
        if POS_ID in ids1:
            print(f"NOTE M1: referenced id {POS_ID} present in its own "
                  f"recommendation results (exclude_referenced_ids posture "
                  f"recorded): {ids1}")
        print(f"M1 OK: R1 = {ids1}")

        # ---- M2: by raw vector of the SAME stored vector (metamorphic) ----
        r2 = run("M2 positive=[[10.0,0,0,0]] (by raw vector)",
                 {"positive": [POS_VEC], "limit": 7, "params": {"exact": True}})
        if r2 is None:
            return
        st2, res2, rw2 = r2
        if st2 != 200 or res2 is None:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) — M2: a raw "
                  f"dense vector is a documented RecommendExample variant and "
                  f"must be accepted, got {st2}: {rw2[:250]}")
            return
        ids2 = [p.get("id") for p in res2]
        ids2_filtered = [i for i in ids2 if i != POS_ID]
        if ids2_filtered != ids1:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                  f"metamorphic relation broken: recommending by id {POS_ID} "
                  f"(which fetches exactly the stored vector {POS_VEC}) and by "
                  f"that raw vector must rank the remaining points "
                  f"identically; R1={ids1} vs R2-minus-{POS_ID}={ids2_filtered}"
                  f": {rw2[:250]}")
            return
        print(f"M2 OK: R2 (n={len(ids2)}, 301 at index "
              f"{ids2.index(POS_ID) if POS_ID in ids2 else 'absent'}) minus 301 "
              f"== R1")

        # ---- M3: MIXED variant array [id, raw vector] (spec-legal) ----
        r3 = run("M3 positive=[301, [10.0,0,0,0]] (mixed variants)",
                 {"positive": [POS_ID, POS_VEC], "limit": 6,
                  "params": {"exact": True}})
        if r3 is None:
            return
        st3, res3, rw3 = r3
        if 400 <= st3 <= 499:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) — M3: the "
                  f"spec types positive as array[PointId|vector]; a mixed "
                  f"element array is schema-legal and must be accepted, got "
                  f"{st3}: {rw3[:250]}")
            return
        if st3 != 200 or res3 is None:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — M3: "
                  f"unexpected status {st3}: {rw3[:250]}")
            return
        ids3 = [p.get("id") for p in res3]
        if ids3 != ids1:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — M3: the "
                  f"mixed examples average to the same query vector as M1 "
                  f"(both elements are {POS_VEC}) and the referenced id is "
                  f"still excluded; expected R1={ids1}, got {ids3}: "
                  f"{rw3[:250]}")
            return
        print("M3 OK: mixed-variant array accepted and equivalent to M1")

        # ---- dual-key / no-variant faces (novel_candidate) ----
        reject_legs = [
            ("D1 no-variant object", {"positive": [{"bogus": 1}], "limit": 3}),
            ("D2 half-keyed SparseVector", {"positive": [{"indices": [0, 1]}], "limit": 3}),
            ("D4 non-uuid digit string", {"positive": ["301"], "limit": 3}),
            ("D5 positive absent entirely", {"limit": 3}),
        ]
        for leg, body in reject_legs:
            r = run(leg, body)
            if r is None:
                return
            st, res, rw = r
            if 200 <= st <= 299:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {leg}: "
                      f"the element matches NO RecommendExample variant (or no "
                      f"example exists at all for D5, which the contract's "
                      f"api_endpoints table marks required); silent acceptance "
                      f"is the confirmed untagged-oneOf drop family, got "
                      f"success {st}: {rw[:300]}")
                return
            if st in (400, 422):
                print(f"{leg} OK: rejected with {st} (400-family)")
            elif 400 <= st <= 499:
                print(f"DISPOSITION_NOTE {leg}: status {st} (400-family variant "
                      f"expected; clear rejection recorded): {rw[:200]}")
            else:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {leg}: "
                      f"unexpected status {st}: {rw[:300]}")
                return

        # ---- D3: well-formed SparseVector against a dense vector (NOTE) ----
        r = run("D3 sparse example on dense collection (NOTE)",
                {"positive": [{"indices": [0, 1], "values": [0.1, 0.2]}],
                 "limit": 3})
        if r is None:
            return
        st, res, rw = r
        print(f"NOTE D3: well-formed SparseVector example against the dense "
              f"unnamed vector -> status={st} "
              f"({'rejected' if 400 <= st <= 499 else 'accepted'}; the "
              f"characteristics wording covers FETCHED vectors, so this face "
              f"is recorded, not adjudicated)")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
