#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_recommend_bounds_001
# strategy: strategy3 legal-input acceptance (boundary closure) + below-min
#           rejection matrix on the recommend pagination bounds
# endpoint: points+recommend
# constraint_ids: qdrant_range_points_recommend_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/search/recommend-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (boundary closure: min values themselves must be accepted)
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy3 pagination-bounds closure x qdrant_range_points_recommend_001 —
  the contract fixes: limit is REQUIRED with minimum 1; offset minimum 0
  (spec corroboration: v1.18.x OpenAPI RecommendRequest.limit integer
  minimum 1, listed in required; offset integer minimum 0, nullable).
  Positive legs exercise the boundary closure (G4: min values themselves
  are legal); negative legs challenge each bound. Legs (valid body
  positive=[701] throughout, exact=true for determinism):
    P1 limit=1              (min closure)   -> 200, exactly 1 result
    P2 limit=3, offset=0    (offset min)    -> 200, result is a list
    P3 limit=1000 (modest single-param upper leg, no resource bomb)
                                            -> 200, results <= 5 (all seeded)
    P4 limit=3, offset=100  (past-the-end; spec warns only about perf)
                                            -> 200, empty-or-short list
    N1 limit omitted        (required)      -> 400-family; 2xx = Type1
    N2 limit=0              (< minimum 1)   -> 400-family; 2xx = Type1
    N3 limit=-1             (< minimum 1)   -> 400-family; 2xx = Type1
    N4 offset=-1            (< minimum 0)   -> 400-family; 2xx = Type1
  [chunk_points+recommend semantic coverage — see
   semantic_points_recommend_behavior_001 docstring for the full 7-script
   list; this script = 003 limit/offset bounds closure x range_001]
Oracle: P1..P4 -> HTTP 200 with result a JSON array (P1 len==1; P3 len==5;
  P4 len<=3); N1..N4 -> 400-family 4xx (400/422 satisfy the loose wording
  per R16); any 2xx on N1..N4 = Type1_IllegalSuccess (documented bound not
  enforced); any 4xx on P1..P4 = Type1_IllegalRejection (legal boundary
  closure value wrongly rejected); 5xx with /healthz alive =
  Type3_RuntimeFailure; transport failure -> /healthz re-check then
  SCRIPT_ERROR (constraint qdrant_range_points_recommend_001).
Constraint: qdrant_range_points_recommend_001 — "recommend request
  pagination bounds: limit required with minimum 1; offset minimum 0"
  (evidence_tier: explicit; level: endpoint)

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

POS_ID = 701
SEED = [{"id": POS_ID, "vector": [10.0, 0.0, 0.0, 0.0]}] + [
    {"id": pid, "vector": [x, 0.0, 0.0, 0.0]}
    for pid, x in ((702, 9.4), (703, 9.0), (704, 8.0), (705, 6.0), (706, 3.0))
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
    coll = "srrg" + tag

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
        base = {"positive": [POS_ID], "params": {"exact": True}}

        def run(leg, extra, drop_limit=False):
            body = dict(base)
            body.update(extra)
            if drop_limit:
                body.pop("limit", None)
            st, bd, rw = safe_request("POST", rpath, json=body, timeout=60)
            print(f"{leg} -> status={st}")
            print(f"raw: {rw[:300]}")
            if st == -1:
                transport_dead(leg)
                return None
            if handle_5xx(st, rw, leg):
                return None
            return st, get_results(bd), rw

        # ---- positive legs: boundary closure must be ACCEPTED ----
        r = run("P1 limit=1 (min closure)", {"limit": 1})
        if r is None:
            return
        st, res, rw = r
        if st != 200 or res is None or len(res) != 1:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) — P1: limit=1 "
                  f"is the documented minimum and must return 200 with exactly 1 "
                  f"result; got status={st}, len={None if res is None else len(res)}: "
                  f"{rw[:250]}")
            return
        print("P1 OK: min limit accepted with exactly 1 result")

        r = run("P2 limit=3 offset=0 (offset min)", {"limit": 3, "offset": 0})
        if r is None:
            return
        st, res, rw = r
        if st != 200 or res is None:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) — P2: offset=0 "
                  f"is the documented minimum and must be accepted, got {st}: "
                  f"{rw[:250]}")
            return
        print(f"P2 OK: offset=0 accepted ({len(res)} results)")

        r = run("P3 limit=1000 (modest upper leg)", {"limit": 1000})
        if r is None:
            return
        st, res, rw = r
        if st != 200 or res is None:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) — P3: limit=1000 "
                  f"is above the minimum with no documented maximum and must be "
                  f"accepted, got {st}: {rw[:250]}")
            return
        if len(res) > 5:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — P3: only 5 "
                  f"recommendable points exist (6 seeded minus the referenced "
                  f"positive), got {len(res)}: {rw[:250]}")
            return
        print(f"P3 OK: large legal limit accepted, capped at {len(res)} results")

        r = run("P4 limit=3 offset=100 (past the end)", {"limit": 3, "offset": 100})
        if r is None:
            return
        st, res, rw = r
        if st != 200 or res is None:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) — P4: a large "
                  f"but legal offset must be accepted (spec warns about perf "
                  f"only), got {st}: {rw[:250]}")
            return
        if len(res) > 3:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — P4: "
                  f"limit=3 must cap the page, got {len(res)}: {rw[:250]}")
            return
        print(f"P4 OK: past-the-end offset accepted, page len={len(res)}")

        # ---- negative legs: below-min / required-absent must be REJECTED ----
        neg_legs = [
            ("N1 limit omitted (required)", {"offset": 0}, True),
            ("N2 limit=0 (< min 1)", {"limit": 0}, False),
            ("N3 limit=-1 (< min 1)", {"limit": -1}, False),
            ("N4 offset=-1 (< min 0)", {"limit": 3, "offset": -1}, False),
        ]
        for leg, extra, drop in neg_legs:
            r = run(leg, extra, drop_limit=drop)
            if r is None:
                return
            st, res, rw = r
            if 200 <= st <= 299:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {leg}: "
                      f"the documented pagination bound is not enforced, got "
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

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
