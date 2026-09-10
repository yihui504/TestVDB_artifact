#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_recommend_semantics_001
# strategy: strategy5 search-semantic correctness (ranking + documented
#           average_vector steering formula)
# endpoint: points+recommend
# constraint_ids: qdrant_behavioral_points_recommend_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/search/recommend-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift — the published formula is easy to
#            implement without the negative subtraction)
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy5 ranking semantics x qdrant_behavioral_points_recommend_001 —
  the contract's valid face ("valid recommend returns HTTP 200 with scored
  points") carries the ranking semantics; the versioned spec pins them
  further: RecommendStrategy.average_vector builds "a single query with
  the formula query = avg_pos + avg_pos - avg_neg. Then performs normal
  search." Geometry (dim-4 Euclid, all points on the x-axis; exact=true so
  HNSW non-determinism (by-design) is out of the picture):
    universe leg 1: 301 at x=10.0 (the POSITIVE), candidates strictly
    left of it: 303 x=9.3, 304 x=9.0, 305 x=8.0, 306 x=6.0, 307 x=3.0,
    308 x=0.0 — every candidate lies left of BOTH average_vector readings
    (c=avg_pos=10 and c=2*avg_pos=20), so the ranking = descending x is
    invariant to that spec ambiguity (R39: no invented oracle — the
    expected table is derived from the seed formula itself, R41).
    L1 positive=[301], no negative, limit=6
       -> 200, ids == expected_order(c in {10,20}) == [303,304,305,306,307,308]
    then 302 at x=10.9 is upserted (absent during L1 so the universe stays
    left-only), and the negative steers the query point to
    c = 2*10.0 - 10.9 = 9.1 (both formula readings agree here):
    L2 positive=[301], negative=[302], limit=6
       -> 200, ids == [304,303,305,306,307,308] (the 303/304 head flips
          vs L1 — the steering must be OBSERVABLE); accepted alternative:
          the same list with 302 ranked at its own distance (absorbs the
          by-design ambiguity whether negative ids are excluded from the
          result alongside positive ids)
    L3 structural: scores non-increasing down each ranked list (any
       monotone score mapping of a distance ranking must be)
  [chunk_points+recommend semantic coverage — see
   semantic_points_recommend_behavior_001 docstring for the full 7-script
   list; this script = 005 ranking + steering formula x behavioral_001]
Oracle: L1 -> HTTP 200 with exactly 6 results in id order
  [303,304,305,306,307,308] (expected table computed from the seed, not
  hand-written); L2 -> 200 with ids equal to expected_order(9.1) excluding
  {301,302} (or that list with 302 at its distance rank); L1 head != L2
  head (steering observable; equal heads = documented formula not
  implemented = Type4); scores non-increasing within each list (Type4 if
  violated); 2xx with a different id order = Type4_StateLogicViolation
  (documented formula/ranking not implemented); non-200 4xx on L1/L2 =
  Type1_IllegalRejection; 5xx with /healthz alive = Type3_RuntimeFailure;
  transport failure -> /healthz re-check then SCRIPT_ERROR (constraint
  qdrant_behavioral_points_recommend_001).
Constraint: qdrant_behavioral_points_recommend_001 — "valid recommend
  returns HTTP 200 with scored points" (evidence_tier: explicit; level:
  endpoint); formula corroboration: RecommendStrategy.average_vector
  description in the v1.18.x OpenAPI shard ("query = avg_pos + avg_pos -
  avg_neg", then normal search)

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

# --- the ONE seed table (R41: expectations derive from it, never hand-written) ---
POS_ID = 301
LEG1_X = {POS_ID: 10.0, 303: 9.3, 304: 9.0, 305: 8.0, 306: 6.0, 307: 3.0, 308: 0.0}
NEG_ID = 302
NEG_X = 10.9
ALL_X = dict(LEG1_X)
ALL_X[NEG_ID] = NEG_X


def expected_order(c, table, exclude):
    """Rank remaining ids by |c - x| ascending (Euclid on the x-axis)."""
    cands = [(pid, x) for pid, x in table.items() if pid not in exclude]
    return [pid for pid, _ in sorted(cands, key=lambda t: abs(c - t[1]))]


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
    coll = "srsc" + tag

    # --- derive the expected tables from the seed formula (R41) ---
    exp_l1_a = expected_order(LEG1_X[POS_ID], LEG1_X, {POS_ID})      # c = avg_pos
    exp_l1_b = expected_order(2.0 * LEG1_X[POS_ID], LEG1_X, {POS_ID})  # c = 2*avg_pos
    if exp_l1_a != exp_l1_b:
        print(f"VERDICT: SCRIPT_ERROR — test design degenerate: the left-only "
              f"geometry must make both average_vector readings rank "
              f"identically ({exp_l1_a} vs {exp_l1_b})")
        return
    exp_l1 = exp_l1_a
    c_l2 = 2.0 * ALL_X[POS_ID] - NEG_X  # documented formula, single reading
    exp_l2_strict = expected_order(c_l2, ALL_X, {POS_ID, NEG_ID})
    exp_l2_with_neg = expected_order(c_l2, ALL_X, {POS_ID})
    exp_l2_with_neg_capped = exp_l2_with_neg[:6]  # limit=6 page if neg not excluded
    if exp_l2_strict[0] == exp_l1[0]:
        print(f"VERDICT: SCRIPT_ERROR — test design degenerate: steering must "
              f"be observable (L1 head {exp_l1[0]} == L2 head {exp_l2_strict[0]})")
        return
    print(f"expected L1 (c-invariant): {exp_l1}")
    print(f"expected L2 strict (c={c_l2:.3f}, excl pos+neg): {exp_l2_strict}")
    print(f"expected L2 with-neg alternative (capped to limit): {exp_l2_with_neg_capped}")

    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        seed1 = [{"id": pid, "vector": [x, 0.0, 0.0, 0.0]} for pid, x in LEG1_X.items()]
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": seed1}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert leg1 universe failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return
        rpath = f"/collections/{coll}/points/recommend"

        # ---- L1: positive-only ranking (invariant to both c readings) ----
        s1, b1, raw1 = safe_request("POST", rpath,
                                    json={"positive": [POS_ID], "limit": 6,
                                          "params": {"exact": True}}, timeout=60)
        print(f"L1 positive=[{POS_ID}] -> status={s1}")
        print(f"raw: {raw1[:400]}")
        if s1 == -1:
            transport_dead("L1"); return
        if handle_5xx(s1, raw1, "L1"):
            return
        res1 = get_results(b1)
        if s1 != 200 or res1 is None:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) — L1: the "
                  f"documented valid face must return 200 with a result array, "
                  f"got {s1}: {raw1[:250]}")
            return
        ids1 = [p.get("id") for p in res1]
        scores1 = [float(p.get("score", 0.0)) for p in res1]
        if len(ids1) != 6 or ids1 != exp_l1:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — L1: "
                  f"recommend by id {POS_ID} must rank the remaining points by "
                  f"distance from the average_vector query point (expected "
                  f"{exp_l1} from the seed geometry; referenced id {POS_ID} "
                  f"excluded by design), got {ids1}: {raw1[:250]}")
            return
        print("L1 OK: ranking matches the c-invariant expected table")

        # ---- upsert the negative anchor AFTER L1 (keeps L1 universe left-only) ----
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": [{"id": NEG_ID,
                                                   "vector": [NEG_X, 0.0, 0.0, 0.0]}]},
                                 params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert negative anchor failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return

        # ---- L2: negative steering per the documented formula ----
        s2, b2, raw2 = safe_request("POST", rpath,
                                    json={"positive": [POS_ID], "negative": [NEG_ID],
                                          "limit": 6, "params": {"exact": True}},
                                    timeout=60)
        print(f"L2 positive=[{POS_ID}] negative=[{NEG_ID}] -> status={s2}")
        print(f"raw: {raw2[:400]}")
        if s2 == -1:
            transport_dead("L2"); return
        if handle_5xx(s2, raw2, "L2"):
            return
        res2 = get_results(b2)
        if s2 != 200 or res2 is None:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) — L2: the "
                  f"documented valid face must return 200 with a result array, "
                  f"got {s2}: {raw2[:250]}")
            return
        ids2 = [p.get("id") for p in res2]
        scores2 = [float(p.get("score", 0.0)) for p in res2]
        if ids2 != exp_l2_strict and ids2 != exp_l2_with_neg_capped:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — L2: the "
                  f"versioned spec pins average_vector to query = avg_pos + "
                  f"avg_pos - avg_neg = {c_l2:.3f}; the ranking must be "
                  f"{exp_l2_strict} (or {exp_l2_with_neg_capped} if negatives "
                  f"are not excluded from results), got {ids2}: {raw2[:250]}")
            return
        if ids2[0] == ids1[0]:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — L2: the "
                  f"negative example must move the query point (documented "
                  f"formula c={c_l2:.3f} flips the head vs L1), but the head is "
                  f"unchanged ({ids2[0]}): {raw2[:250]}")
            return
        print("L2 OK: steering ranking matches the documented formula "
              f"(head flip {ids1[0]} -> {ids2[0]})")

        # ---- L3: structural monotonicity of the ranked scores ----
        for name, sc in (("L1", scores1), ("L2", scores2)):
            if any(sc[i] < sc[i + 1] - 1e-9 for i in range(len(sc) - 1)):
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                      f"{name}: ranked results must be non-increasing in score, "
                      f"got {sc}: {(raw1 if name == 'L1' else raw2)[:250]}")
                return
        print("L3 OK: scores non-increasing in both ranked lists")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
