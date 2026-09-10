#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_query_id_order_001
# strategy: strategy1 behavioral-contract attack (query-omission id-order
#           semantics) + determinism metamorphic re-run
# endpoint: points+query
# constraint_ids: qdrant_behavioral_points_query_004
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift — the OpenAPI QueryRequest
#            description fixes this: "If missing without prefetches, returns
#            points ordered by their IDs")
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy1 id-order semantics x qdrant_behavioral_points_query_004 —
  the contract (from the published OpenAPI QueryRequest.query description)
  states: query may be OMITTED; without prefetches the response contains
  points ordered by their ids. 15 points upserted in SHUFFLED id order
  (insert order must not masquerade as id order), payload city A/B split
  8/7. Legs:
    F1 no query, no prefetch, limit=15 -> ids strictly ascending 501..515
    F2 same request repeated           -> identical sequence (determinism
                                          metamorphic re-run of F1)
    F3 no query, limit=5               -> exactly sorted(ids)[:5]
    F4 no query + filter must city=A limit=15 -> exactly the 8 A-ids,
                                          still ascending (filter intersects
                                          the id order, never scrambles it)
    F5 query omitted WITH prefetch present (the other documented form)
       -> 200 with result.points a list (legality face only; the contract
          does not fix the content of this form)
  [chunk_points+query semantic coverage — see variant_domain_001 for the
  full 10-script coverage list; this script = id-order x
  qdrant_behavioral_points_query_004]
Oracle: F1 -> HTTP 200 with result.points ids == [501..515] strictly
  ascending (upsert order was shuffled, so ascending order can only come
  from the documented id-order rule); F2 == F1 exactly; F3 == first 5 ids;
  F4 -> exactly the 8 city-A ids ascending; F5 -> 200 with a points list.
  Non-ascending or wrong-set results = Type4_StateLogicViolation; 4xx on
  F1..F5 = Type1_IllegalSuccess (documented request shape rejected); 5xx
  with /healthz alive = Type3_RuntimeFailure; transport failure ->
  /healthz re-check then SCRIPT_ERROR (constraint
  qdrant_behavioral_points_query_004).
Constraint: qdrant_behavioral_points_query_004 (bare id) — "query absent and
  no prefetch: the response contains points ordered by id (documented
  behavior)" (evidence_tier: explicit; level: endpoint)

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
N = 15
ALL_IDS = list(range(501, 501 + N))
CITY_A_IDS = ALL_IDS[:8]           # 501..508
SHUFFLED = [512, 503, 515, 501, 508, 505, 513, 502, 510, 507, 514, 504,
            511, 506, 509]
SEED = [{"id": i,
         "vector": [float((i - 501) % 4), 1.0, 0.25, 0.5],
         "payload": {"city": "A" if i in CITY_A_IDS else "B"}}
        for i in SHUFFLED]


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
    coll = "spqI1" + tag

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

        def leg(leg_name, body_json):
            s, body, raw = safe_request("POST", qpath, json=body_json, timeout=60)
            print(f"{leg_name} -> status={s}")
            print(f"raw: {raw[:300]}")
            if s == -1:
                transport_dead(leg_name)
                return None
            if handle_5xx(s, raw, leg_name):
                return None
            if 400 <= s <= 499:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {leg_name}: "
                      f"documented query-omission request rejected with {s}: "
                      f"{raw[:250]}")
                return "DEFECT"
            pts = get_points(body)
            if s != 200 or pts is None:
                print(f"VERDICT: SCRIPT_ERROR — {leg_name} unexpected status {s}; "
                      f"no defect conclusion")
                return None
            return [p.get("id") for p in pts]

        f1 = leg("F1 no query limit=15", {"limit": 15})
        if f1 in (None, "DEFECT"):
            return
        if f1 != sorted(ALL_IDS):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F1: query "
                  f"omitted without prefetch must return points ordered by id "
                  f"(upsert was shuffled to {SHUFFLED[:4]}...), expected "
                  f"{sorted(ALL_IDS)}, got {f1}")
            return
        print("F1 OK: ids strictly ascending despite shuffled upsert order")

        f2 = leg("F2 rerun of F1", {"limit": 15})
        if f2 in (None, "DEFECT"):
            return
        if f2 != f1:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F2: id-order "
                  f"mode is documented deterministic, rerun differs: {f2} != {f1}")
            return
        print("F2 OK: deterministic on rerun")

        f3 = leg("F3 no query limit=5", {"limit": 5})
        if f3 in (None, "DEFECT"):
            return
        if f3 != sorted(ALL_IDS)[:5]:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F3: "
                  f"limit=5 must return the first 5 ids ascending "
                  f"{sorted(ALL_IDS)[:5]}, got {f3}")
            return
        print("F3 OK: limit slices the id order")

        f4 = leg("F4 no query + filter city=A", {
            "limit": 15,
            "filter": {"must": [{"key": "city", "match": {"value": "A"}}]}})
        if f4 in (None, "DEFECT"):
            return
        if f4 != sorted(CITY_A_IDS):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F4: filter "
                  f"city=A in id-order mode must return exactly the 8 A-ids "
                  f"ascending {sorted(CITY_A_IDS)}, got {f4}")
            return
        print("F4 OK: filtered id-order is the ascending A-subset")

        f5 = leg("F5 query omitted with prefetch", {
            "prefetch": [{"query": {"nearest": [0.0, 1.0, 0.25, 0.5]},
                          "limit": 5}],
            "limit": 5})
        if f5 in (None, "DEFECT"):
            return
        if len(f5) == 0:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F5: query "
                  f"omission WITH prefetch is the other documented legal form; "
                  f"got an empty result with 200")
            return
        print(f"F5 OK: query-omission with prefetch accepted (ids {f5}); content "
              f"of this documented form is not fixed by the contract — legality "
              f"face only")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
