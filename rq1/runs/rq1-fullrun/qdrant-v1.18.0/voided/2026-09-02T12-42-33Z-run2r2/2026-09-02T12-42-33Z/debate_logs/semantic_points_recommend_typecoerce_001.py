#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_recommend_typecoerce_001
# strategy: strategy4 implicit type-conversion attack on the recommend
#           pagination params (limit / offset)
# endpoint: points+recommend
# constraint_ids: qdrant_range_points_recommend_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/search/recommend-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust)
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy4 type-coercion x qdrant_range_points_recommend_001 —
  the contract types limit/offset as integers (limit min 1 required, offset
  min 0; spec corroboration: v1.18.x OpenAPI RecommendRequest.limit type
  integer; offset type [integer, null]). Non-integer spellings that would
  need silent coercion to satisfy the range must be REJECTED; the one
  spec-legal non-integer spelling (offset=null, explicitly nullable) must
  be ACCEPTED — the G4 pairing that keeps the rejection faces honest.
  Legs (valid body positive=[721] throughout, exact=true):
    C0 limit=3 (integer control)      -> 200 (setup sanity)
    T1 limit="3"   (numeric string)   -> 400-family; 2xx = coercion = Type1
    T2 limit=3.0   (float)            -> 400-family; 2xx = Type1
    T3 limit=true  (boolean)          -> 400-family; 2xx = Type1
    T4 limit=null  (null, NOT nullable)-> 400-family; 2xx = Type1
    T5 offset="1"  (numeric string)   -> 400-family; 2xx = Type1
    T6 offset=1.5  (fractional float) -> 400-family; 2xx = Type1
    T7 offset=true (boolean)          -> 400-family; 2xx = Type1
    P1 offset=null (spec-nullable)    -> 200; 4xx = Type1_IllegalRejection
  [chunk_points+recommend semantic coverage — see
   semantic_points_recommend_behavior_001 docstring for the full 7-script
   list; this script = 004 limit/offset type-coercion x range_001]
Oracle: C0/P1 -> HTTP 200 (P1 result a JSON array); T1..T7 -> 400-family
  4xx (400/422 per R16); any 2xx on T1..T7 = Type1_IllegalSuccess
  (non-integer spelling silently coerced past the documented integer
  range); 4xx on P1 = Type1_IllegalRejection (spec-derived nullable
  offset wrongly rejected — D3b: spec wins); 5xx with /healthz alive =
  Type3_RuntimeFailure; transport failure -> /healthz re-check then
  SCRIPT_ERROR (constraint qdrant_range_points_recommend_001).
Constraint: qdrant_range_points_recommend_001 — "limit minimum 1
  (required); offset minimum 0" over integer-typed params (evidence_tier:
  explicit; level: endpoint)

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

POS_ID = 721
SEED = [{"id": POS_ID, "vector": [10.0, 0.0, 0.0, 0.0]}] + [
    {"id": pid, "vector": [x, 0.0, 0.0, 0.0]}
    for pid, x in ((722, 9.4), (723, 9.0), (724, 8.0), (725, 6.0), (726, 3.0))
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
    coll = "srtc" + tag

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
            print(f"raw: {rw[:300]}")
            if st == -1:
                transport_dead(leg)
                return None
            if handle_5xx(st, rw, leg):
                return None
            return st, get_results(bd), rw

        # ---- C0 sanity: integer control must be 200 ----
        r = run("C0 limit=3 (control)",
                {"positive": [POS_ID], "limit": 3, "params": {"exact": True}})
        if r is None:
            return
        st, res, rw = r
        if st != 200 or res is None:
            print(f"VERDICT: SCRIPT_ERROR — control face not 200 (status={st}); "
                  f"coercion faces not measurable: {rw[:200]}")
            return
        print("C0 OK: integer limit accepted")

        # ---- coercion faces on limit / offset (must be rejected) ----
        coerce_legs = [
            ("T1 limit='3' (string)", {"positive": [POS_ID], "limit": "3"}),
            ("T2 limit=3.0 (float)", {"positive": [POS_ID], "limit": 3.0}),
            ("T3 limit=true (bool)", {"positive": [POS_ID], "limit": True}),
            ("T4 limit=null (not nullable)", {"positive": [POS_ID], "limit": None}),
            ("T5 offset='1' (string)", {"positive": [POS_ID], "limit": 3, "offset": "1"}),
            ("T6 offset=1.5 (fractional)", {"positive": [POS_ID], "limit": 3, "offset": 1.5}),
            ("T7 offset=true (bool)", {"positive": [POS_ID], "limit": 3, "offset": True}),
        ]
        for leg, body in coerce_legs:
            r = run(leg, body)
            if r is None:
                return
            st, res, rw = r
            if 200 <= st <= 299:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {leg}: "
                      f"non-integer spelling silently accepted as a valid "
                      f"integer param (implicit coercion past the documented "
                      f"integer range), got success {st}: {rw[:300]}")
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

        # ---- P1: offset=null is spec-derived LEGAL (nullable) -> 200 ----
        r = run("P1 offset=null (spec-nullable)",
                {"positive": [POS_ID], "limit": 3, "offset": None,
                 "params": {"exact": True}})
        if r is None:
            return
        st, res, rw = r
        if st != 200 or res is None:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) — P1: the "
                  f"v1.18.x spec types offset as [integer, null]; null must be "
                  f"accepted like an absent offset, got {st}: {rw[:300]}")
            return
        print(f"P1 OK: nullable offset accepted ({len(res)} results)")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
