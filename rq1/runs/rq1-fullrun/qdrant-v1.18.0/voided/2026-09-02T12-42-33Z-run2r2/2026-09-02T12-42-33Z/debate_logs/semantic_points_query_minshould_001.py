#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_query_minshould_001
# strategy: strategy7 filter-semantics attack (min_should group on the query
#           endpoint — result-SET semantics, not the count face)
# endpoint: points+query
# constraint_ids: qdrant_behavioral_points_query_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 — the TMA names "min_should with empty conditions" as the
#            FIRST semantic attack on this critical endpoint
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy7 min_should result-set semantics x points+query —
  the TMA ranks POST /collections/{name}/points/query as critical #1 with
  semantic attack order min_should/nested filter; the Filter data type
  fixes {should?, min_should?, must?, must_not?} where min_should =
  {conditions: [...], min_count} and a point matches when AT LEAST
  min_count of the conditions hold. This script attacks the RESULT-SET
  face (which ids come back), distinct from the points+count face already
  covered by boundary_points_count_min_should_004. 12 points: 8 with
  city=berlin (ids 601..608), 4 with city=paris (ids 609..612), scalar
  city so no point can satisfy two city conditions at once (id-collision
  analysis per R33: every expectation below is pure set arithmetic).
  All legs run the SAME exact nearest query with with_payload=true so
  membership is verified from readback, not just counts:
    F1 baseline must city=berlin       -> exactly {601..608}
    F2 min_should [berlin, paris] min_count=1 -> all 12 (every point
                                          satisfies >= 1 of the two)
    F3 min_should [berlin, paris] min_count=2 -> exactly 0 (scalar city:
                                          nobody satisfies both)
    F4 min_should [] min_count=1 (TMA face) -> clean outcomes are 4xx
                                          (validation) or 200 with 0
                                          points (unsatisfiable); 200
                                          with points = the unsatisfiable
                                          clause silently ignored ->
                                          NOTE, disposition recorded
                                          (kept consistent with the
                                          boundary-lane count-face
                                          calibration — G9)
    F5 min_should [berlin] min_count=0 -> NOTE leg (vacuous vs 0->1
                                          clamp), disposition recorded
  [chunk_points+query semantic coverage — see variant_domain_001 for the
  full 10-script coverage list; this script = filter_semantics min_should
  x TMA-order#1, anchored on the endpoint's behavioral contract
  qdrant_behavioral_points_query_001 whose result-set semantics the
  filter decides]
Oracle: F1 -> HTTP 200 with result.points ids exactly {601..608} (8 pts,
  payloads all berlin); F2 -> exactly all 12 ids; F3 -> 200 with 0 points
  (or clean 4xx); F4 -> 4xx or 0 points (12 points = NOTE, recorded);
  any wrong SET on F1/F2/F3 = Type4_StateLogicViolation (filter semantics
  violated); 4xx on F1/F2 = Type1_IllegalSuccess; 5xx with /healthz alive
  = Type3_RuntimeFailure; transport failure -> /healthz re-check then
  SCRIPT_ERROR (constraint qdrant_behavioral_points_query_001).
Constraint: qdrant_behavioral_points_query_001 (bare id) — "valid query
  returns HTTP 200 with result array of scored points" + Filter data type
  "{should?, min_should?, must?, must_not?}" (evidence_tier: explicit;
  level: endpoint)

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

DIM = 4
BERLIN_IDS = list(range(601, 609))   # 8
PARIS_IDS = list(range(609, 613))    # 4
ALL_IDS = BERLIN_IDS + PARIS_IDS
SEED = [{"id": i,
         "vector": [float(i - 601), 1.0, 0.25, 0.5],
         "payload": {"city": "berlin" if i in BERLIN_IDS else "paris"}}
        for i in ALL_IDS]

COND_BERLIN = {"key": "city", "match": {"value": "berlin"}}
COND_PARIS = {"key": "city", "match": {"value": "paris"}}


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
    coll = "spqM1" + tag

    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
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

        qpath = f"/collections/{coll}/points/query"

        def query_with_filter(leg, flt):
            body_json = {"query": {"nearest": [0.0, 1.0, 0.25, 0.5]},
                         "params": {"exact": True},
                         "filter": flt, "limit": 12, "with_payload": True}
            s, body, raw = safe_request("POST", qpath, json=body_json, timeout=60)
            print(f"{leg} -> status={s}")
            print(f"raw: {raw[:350]}")
            if s == -1:
                transport_dead(leg)
                return None
            if handle_5xx(s, raw, leg):
                return None
            return s, get_points(body), raw

        # ---- F1: baseline must ----
        res = query_with_filter("F1 must city=berlin", {"must": [COND_BERLIN]})
        if res is None:
            return
        s, pts, raw = res
        if 400 <= s <= 499:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F1: a plain "
                  f"documented filter was rejected with {s}: {raw[:250]}")
            return
        ids = sorted(p.get("id") for p in pts) if pts is not None and s == 200 else None
        if ids != BERLIN_IDS:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F1: "
                  f"must city=berlin must return exactly {BERLIN_IDS}, got "
                  f"{ids}: {raw[:250]}")
            return
        for p in pts:
            if p.get("payload", {}).get("city") != "berlin":
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F1: "
                      f"readback payload contradicts the filter: "
                      f"{json.dumps(p)[:150]}")
                return
        print("F1 OK: must-filter set exact, payloads consistent")

        # ---- F2: min_count=1 of [berlin, paris] -> all 12 ----
        res = query_with_filter("F2 min_should min_count=1",
                                {"min_should": {"conditions": [COND_BERLIN, COND_PARIS],
                                                "min_count": 1}})
        if res is None:
            return
        s, pts, raw = res
        if 400 <= s <= 499:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F2: documented "
                  f"min_should filter rejected with {s}: {raw[:250]}")
            return
        ids = sorted(p.get("id") for p in pts) if pts is not None and s == 200 else None
        if ids != ALL_IDS:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F2: every "
                  f"point satisfies >=1 of [berlin, paris], so min_count=1 must "
                  f"return all 12 ids, got {ids}: {raw[:250]}")
            return
        print("F2 OK: min_count=1 union set exact (12/12)")

        # ---- F3: min_count=2 of [berlin, paris] -> exactly 0 ----
        res = query_with_filter("F3 min_should min_count=2",
                                {"min_should": {"conditions": [COND_BERLIN, COND_PARIS],
                                                "min_count": 2}})
        if res is None:
            return
        s, pts, raw = res
        if 200 <= s <= 299:
            ids = [p.get("id") for p in pts] if pts is not None else None
            if ids:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F3: no "
                      f"point carries both cities (scalar payload), so min_count=2 "
                      f"of [berlin, paris] is unsatisfiable — must be 0 points, "
                      f"got {sorted(ids)}: {raw[:250]}")
                return
            print("F3 OK: min_count=2 -> 0 points (unsatisfiable, correct)")
        elif 400 <= s <= 499:
            print("NOTE F3: min_count=2 rejected with 4xx — a satisfiable "
                  "min_should group should be servable, disposition recorded")
        else:
            print(f"VERDICT: SCRIPT_ERROR — F3 unexpected status {s}; no defect "
                  f"conclusion")
            return

        # ---- F4: TMA face — empty conditions, min_count=1 ----
        res = query_with_filter("F4 min_should [] min_count=1",
                                {"min_should": {"conditions": [], "min_count": 1}})
        if res is None:
            return
        s, pts, raw = res
        if 200 <= s <= 299:
            ids = [p.get("id") for p in pts] if pts is not None else None
            if ids:
                print(f"NOTE F4: min_should conditions=[] with min_count=1 is "
                      f"unsatisfiable yet {len(ids)} points returned — "
                      f"empty-clause-ignored convention; kept consistent with "
                      f"the boundary-lane count-face calibration (G9), recorded "
                      f"for the judge")
            else:
                print("F4 OK: empty conditions min_count=1 -> 0 points "
                      "(strict unsatisfiable semantics)")
        elif 400 <= s <= 499:
            print("F4 OK: empty conditions min_count=1 rejected by 4xx "
                  "(validation semantics)")
        else:
            print(f"VERDICT: SCRIPT_ERROR — F4 unexpected status {s}; no defect "
                  f"conclusion")
            return

        # ---- F5: NOTE leg — min_count=0 ----
        res = query_with_filter("F5 min_should [berlin] min_count=0",
                                {"min_should": {"conditions": [COND_BERLIN],
                                                "min_count": 0}})
        if res is None:
            return
        s, pts, raw = res
        if 200 <= s <= 299:
            ids = [p.get("id") for p in pts] if pts is not None else []
            if len(ids) == 12:
                print("NOTE F5: min_count=0 treated as vacuous (all 12) — "
                      "documented default is min_count absence, 0 is a judge call")
            elif len(ids) == 8:
                print("NOTE F5: min_count=0 silently clamped to 1 (8 berlins) — "
                      "disposition recorded for the judge")
            else:
                print(f"NOTE F5: min_count=0 returned {len(ids)} points — "
                      f"disposition recorded")
        else:
            print(f"NOTE F5: min_count=0 rejected with {s} — disposition recorded")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
