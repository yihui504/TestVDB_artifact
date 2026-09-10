#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_query_byid_lookup_001
# strategy: strategy6 metamorphic attack (by-id query == by-stored-vector query)
#           + state-constraint negative faces (lookup mismatch / missing point)
# endpoint: points+query
# constraint_ids: qdrant_state_points_query_001
# source_url: https://qdrant.tech/documentation/search/search/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-05 (Documentation Drift — the by-id lookup promise is easy to
#            implement with a stale/cached vector path)
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy6 by-id-lookup equivalence x qdrant_state_points_query_001 —
  the contract states: by-id lookup (query = point id) fetches the STORED
  vector of that point, and fetched vectors that do not match the
  characteristics of the using vector make the request ERROR. Two
  collections: A (Euclid dim 4, 5 collinear points with distinct graded
  distances, so the exact ranking is derivable) and B (Euclid dim 8 —
  a different vector characteristic). Legs (exact=true for determinism):
    L1 query = 301 (bare point id, by-id lookup) on A
       -> 200; ranking must equal the by-vector ranking
    L2 query = {"nearest": v(301)} on A
       -> must be IDENTICAL to L1 in ids AND scores (the metamorphic
          relation: by-id == by-stored-vector)
    L3 by-id of a NONEXISTENT point 9999 on A
       -> 4xx error (nothing to fetch); 2xx = Type4 (invented vector)
    L4 by-id 901 (exists only in B, dim 8) + lookup_from B, queried on A
       -> 4xx error (characteristics mismatch is documented to error);
          2xx = Type4 (silent cross-dimension success), 5xx = Type3
    L5 (NOTE) by-id 901 WITHOUT lookup_from on A
       -> disposition recorded (missing local point), not judged
  [chunk_points+query semantic coverage — see variant_domain_001 for the
  full 10-script coverage list; this script = metamorphic by-id-lookup x
  qdrant_state_points_query_001]
Oracle: L1 and L2 return HTTP 200 with identical result.points id lists
  [301, 302, 303, 304, 305] (graded distances 0,1,2,3,4) and equal scores
  within 1e-6 (first = 1.0 Euclid self-match); L3/L4 -> 400-family 4xx;
  any 2xx on L3/L4 = Type4_StateLogicViolation; 5xx with /healthz alive =
  Type3_RuntimeFailure; transport failure -> /healthz re-check then
  SCRIPT_ERROR (constraint qdrant_state_points_query_001).
Constraint: qdrant_state_points_query_001 (bare id) — "by-id query uses the
  referenced point's stored vector; if it does not match the using vector
  characteristics the request errors" (evidence_tier: explicit; level: system)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+query        -> POST /collections/{collection_name}/points/query
  points+upsert       -> PUT  /collections/{collection_name}/points
  collections+create  -> PUT  /collections/{collection_name}
  collections+delete  -> DELETE /collections/{collection_name}
  healthz             -> GET  /healthz
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

# A: dim 4 Euclid; point 30i at distance i-1 from the query point 301
VEC_A = {301: [1.0, 0.0, 0.0, 0.0], 302: [2.0, 0.0, 0.0, 0.0],
         303: [3.0, 0.0, 0.0, 0.0], 304: [4.0, 0.0, 0.0, 0.0],
         305: [5.0, 0.0, 0.0, 0.0]}
EXPECTED_ORDER = [301, 302, 303, 304, 305]
# B: dim 8 Euclid — different vector characteristic than A
SEED_B = [{"id": 901, "vector": [1.0] * 8}, {"id": 902, "vector": [2.0] * 8}]


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


def get_points(body):
    if isinstance(body, dict):
        r = body.get("result")
        if isinstance(r, dict) and isinstance(r.get("points"), list):
            return r["points"]
    return None


def main():
    tag = uuid.uuid4().hex[:8]
    coll_a = "spqLA" + tag
    coll_b = "spqLB" + tag

    s, _, raw = safe_request("PUT", f"/collections/{coll_a}",
                             json={"vectors": {"size": 4, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create A failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    s, _, raw = safe_request("PUT", f"/collections/{coll_b}",
                             json={"vectors": {"size": 8, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create B failed status={s}: {raw[:300]}")
        try:
            safe_request("DELETE", f"/collections/{coll_a}", timeout=60)
        except Exception:
            pass
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        seed_a = [{"id": pid, "vector": v} for pid, v in VEC_A.items()]
        s, _, raw = safe_request("PUT", f"/collections/{coll_a}/points",
                                 json={"points": seed_a}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert A failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return
        s, _, raw = safe_request("PUT", f"/collections/{coll_b}/points",
                                 json={"points": SEED_B}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert B failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return

        qpath_a = f"/collections/{coll_a}/points/query"

        # ---- L1: by-id lookup (bare point id) ----
        s1, body1, raw1 = safe_request("POST", qpath_a,
                                       json={"query": 301, "params": {"exact": True},
                                             "limit": 5}, timeout=60)
        print(f"L1 by-id 301 -> status={s1}")
        print(f"raw: {raw1[:400]}")
        if s1 == -1:
            transport_dead("L1 by-id"); return
        if handle_5xx(s1, raw1, "L1 by-id"):
            return
        pts1 = get_points(body1)
        if s1 != 200 or pts1 is None:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — L1: documented "
                  f"by-id lookup rejected with {s1}: {raw1[:250]}")
            return

        # ---- L2: by-vector of the SAME stored vector ----
        s2, body2, raw2 = safe_request("POST", qpath_a,
                                       json={"query": {"nearest": VEC_A[301]},
                                             "params": {"exact": True}, "limit": 5}, timeout=60)
        print(f"L2 by-vector -> status={s2}")
        print(f"raw: {raw2[:400]}")
        if s2 == -1:
            transport_dead("L2 by-vector"); return
        if handle_5xx(s2, raw2, "L2 by-vector"):
            return
        pts2 = get_points(body2)
        if s2 != 200 or pts2 is None:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — L2: documented "
                  f"nearest query rejected with {s2}: {raw2[:250]}")
            return

        ids1 = [p.get("id") for p in pts1]
        ids2 = [p.get("id") for p in pts2]
        scores1 = [float(p.get("score", 0.0)) for p in pts1]
        scores2 = [float(p.get("score", 0.0)) for p in pts2]
        if ids1 != EXPECTED_ORDER:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — L1: by-id "
                  f"lookup of 301 must rank by 301's stored vector "
                  f"({EXPECTED_ORDER} by graded distance), got {ids1}: {raw1[:250]}")
            return
        if ids1 != ids2 or any(abs(a - b) > 1e-6 for a, b in zip(scores1, scores2)):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — metamorphic "
                  f"relation broken: by-id query != by-stored-vector query "
                  f"(ids {ids1} vs {ids2}; scores {scores1} vs {scores2})")
            return
        if abs(scores1[0] - 1.0) > 1e-6:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — L1: by-id "
                  f"self-match score must be 1.0 (Euclid distance 0), got "
                  f"{scores1[0]}: {raw1[:250]}")
            return
        print("L1/L2 OK: by-id == by-stored-vector (ids and scores identical)")

        # ---- L3: by-id of a nonexistent point ----
        s, _, raw = safe_request("POST", qpath_a,
                                 json={"query": 9999, "limit": 3}, timeout=60)
        print(f"L3 by-id 9999 (missing) -> status={s}")
        print(f"raw: {raw[:300]}")
        if s == -1:
            transport_dead("L3 missing point"); return
        if handle_5xx(s, raw, "L3 by-id missing"):
            return
        if 200 <= s <= 299:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — L3: by-id "
                  f"lookup of a point that does not exist cannot fetch any stored "
                  f"vector, yet the query succeeded with {s}: {raw[:250]}")
            return
        print("L3 OK: by-id of missing point rejected by 4xx")

        # ---- L4: cross-collection lookup with mismatched characteristics ----
        s, _, raw = safe_request("POST", qpath_a,
                                 json={"query": 901,
                                       "lookup_from": {"collection": coll_b},
                                       "limit": 3}, timeout=60)
        print(f"L4 lookup_from dim-8 B -> status={s}")
        print(f"raw: {raw[:300]}")
        if s == -1:
            transport_dead("L4 lookup mismatch"); return
        if handle_5xx(s, raw, "L4 lookup mismatch"):
            return
        if 200 <= s <= 299:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — L4: the "
                  f"fetched dim-8 vector from {coll_b} does not match the dim-4 "
                  f"characteristics of {coll_a}; the contract documents an error, "
                  f"got success {s}: {raw[:250]}")
            return
        print("L4 OK: characteristics-mismatched lookup errors with 4xx")

        # ---- L5 (NOTE): by-id 901 without lookup_from on A ----
        s, _, raw = safe_request("POST", qpath_a,
                                 json={"query": 901, "limit": 3}, timeout=60)
        print(f"L5 by-id 901 no lookup_from -> status={s}")
        print(f"raw: {raw[:300]}")
        if s == -1:
            transport_dead("L5"); return
        if handle_5xx(s, raw, "L5 no lookup"):
            return
        print("NOTE L5: by-id 901 without lookup_from -> "
              f"{'4xx (missing local point)' if 400 <= s <= 499 else f'status {s}'} "
              f"— disposition recorded, not judged")

        print("VERDICT: NO_DEFECT")
    finally:
        for c in (coll_a, coll_b):
            try:
                safe_request("DELETE", f"/collections/{c}", timeout=60)
            except Exception:
                pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
