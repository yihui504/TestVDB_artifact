#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_recommend_filter_001
# strategy: strategy7 filter-parameter semantic correctness inside recommend
# endpoint: points+recommend
# constraint_ids: qdrant_behavioral_points_recommend_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/search/recommend-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift / semantic contract)
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy7 filter semantics x qdrant_behavioral_points_recommend_001 —
  the endpoint spec binds the filter parameter to the promise "Look only
  for points which satisfies this conditions" (api_endpoints.parameters
  filter description; Filter data type {should?, min_should?, must?,
  must_not?} with match/range conditions). A recommend query whose filter
  selects a known subset of a seeded universe must return EXACTLY that
  subset, in the recommendation ranking, not the unfiltered set and not a
  superset. Geometry (dim-4 Euclid, x-axis, exact=true; positive 801 at
  x=10 referenced by id, excluded from results by design):
    universe: 802..811 at x = 9.4, 9.0, 8.5, 8.0, 6.0, 5.5, 4.0, 3.5,
              2.0, 0.5 with payload cat alternating A,B,... and n = 1..10
              assigned in descending-x order
    F0 control, no filter -> 200 with all 10 candidates in ranking order
    F1 must/match  cat == A      -> 200 with exactly the 5 A-members,
                                    ranked by distance from the query point
    F2 must/range  n >= 6        -> 200 with exactly ids 807..811 (the
                                    n>=6 tail), ranked
    F3 must_not/match cat == A   -> 200 with exactly the 5 B-members,
                                    ranked (the must_not face of the same
                                    promise, G9 same-family consistency)
  Expected tables are computed from the seed table itself (R41), never
  hand-written; because every candidate sits left of the positive anchor,
  the ranking = descending x for both average_vector readings.
  [chunk_points+recommend semantic coverage — see
   semantic_points_recommend_behavior_001 docstring for the full 7-script
   list; this script = 006 filter semantics x behavioral_001]
Oracle: F0 -> HTTP 200 with 10 ids [802,...,811] in descending-x ranking;
  F1 -> 200 with ids == the 5 A-members ranked (set AND order); F2 -> 200
  with ids == [807,808,809,810,811]; F3 -> 200 with ids == the 5
  B-members ranked; any wrong set (filter ignored / over-selected /
  under-selected) or wrong rank order = Type4_StateLogicViolation;
  non-200 4xx on any face = Type1_IllegalRejection; 5xx with /healthz
  alive = Type3_RuntimeFailure; transport failure -> /healthz re-check
  then SCRIPT_ERROR (constraint qdrant_behavioral_points_recommend_001 +
  endpoint filter promise).
Constraint: qdrant_behavioral_points_recommend_001 — "valid recommend
  returns HTTP 200 with scored points" (evidence_tier: explicit) scoped by
  the endpoint's own filter contract "Look only for points which
  satisfies this conditions"

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

POS_ID = 801
POS_X = 10.0
# the ONE seed table: id -> (x, cat, n); expectations derive from it (R41)
CAND_TABLE = [
    (802, 9.4, "A", 1), (803, 9.0, "B", 2), (804, 8.5, "A", 3), (805, 8.0, "B", 4),
    (806, 6.0, "A", 5), (807, 5.5, "B", 6), (808, 4.0, "A", 7), (809, 3.5, "B", 8),
    (810, 2.0, "A", 9), (811, 0.5, "B", 10),
]


def ranked(pred):
    """Ids of candidates satisfying pred, in recommendation rank order.

    Every candidate x < POS_X <= c for both average_vector readings
    (c = avg_pos = 10 or c = 2*avg_pos = 20), so rank order = descending x.
    """
    chosen = [t for t in CAND_TABLE if pred(t)]
    return [pid for pid, x, _, _ in sorted(chosen, key=lambda t: -t[1])]


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
    coll = "srfs" + tag

    exp_f0 = ranked(lambda t: True)
    exp_f1 = ranked(lambda t: t[2] == "A")            # must/match cat == A
    exp_f2 = ranked(lambda t: t[3] >= 6)              # must/range n >= 6
    exp_f3 = ranked(lambda t: t[2] == "B")            # must_not/match cat == A
    print(f"expected F0: {exp_f0}")
    print(f"expected F1 (cat==A): {exp_f1}")
    print(f"expected F2 (n>=6):   {exp_f2}")
    print(f"expected F3 (cat!=A): {exp_f3}")

    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        seed = [{"id": POS_ID, "vector": [POS_X, 0.0, 0.0, 0.0]}] + [
            {"id": pid, "vector": [x, 0.0, 0.0, 0.0], "payload": {"cat": cat, "n": n}}
            for pid, x, cat, n in CAND_TABLE
        ]
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": seed}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return
        rpath = f"/collections/{coll}/points/recommend"

        def run(leg, extra):
            body = {"positive": [POS_ID], "limit": 10, "params": {"exact": True}}
            body.update(extra)
            st, bd, rw = safe_request("POST", rpath, json=body, timeout=60)
            print(f"{leg} -> status={st}")
            print(f"raw: {rw[:400]}")
            if st == -1:
                transport_dead(leg)
                return None
            if handle_5xx(st, rw, leg):
                return None
            return st, get_results(bd), rw

        def judge(leg, r, expected):
            if r is None:
                return False
            st, res, rw = r
            if st != 200 or res is None:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) — {leg}: "
                      f"a valid filtered recommend must return 200 with a result "
                      f"array, got {st}: {rw[:250]}")
                return False
            ids = [p.get("id") for p in res]
            if ids != expected:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                      f"{leg}: the filter must select exactly {expected} "
                      f"(seed-derived) in ranking order, got {ids}: {rw[:250]}")
                return False
            print(f"{leg} OK: filtered set and rank match the seed-derived table")
            return True

        if not judge("F0 control (no filter)",
                     run("F0 control (no filter)", {}), exp_f0):
            return
        if not judge("F1 must/match cat==A",
                     run("F1 must/match cat==A",
                         {"filter": {"must": [{"key": "cat", "match": {"value": "A"}}]}}),
                     exp_f1):
            return
        if not judge("F2 must/range n>=6",
                     run("F2 must/range n>=6",
                         {"filter": {"must": [{"key": "n", "range": {"gte": 6}}]}}),
                     exp_f2):
            return
        if not judge("F3 must_not/match cat==A",
                     run("F3 must_not/match cat==A",
                         {"filter": {"must_not": [{"key": "cat", "match": {"value": "A"}}]}}),
                     exp_f3):
            return

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
