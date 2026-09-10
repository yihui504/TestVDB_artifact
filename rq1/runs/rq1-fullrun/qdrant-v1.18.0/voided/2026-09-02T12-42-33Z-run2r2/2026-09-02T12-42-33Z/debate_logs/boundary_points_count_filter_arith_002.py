#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_count_filter_arith_002
# strategy: strategy1 boundary-value attack (filter-aware exact-count
#           arithmetic: every expected count derived from the seed set)
# endpoint: points+count
# constraint_ids: qdrant_behavioral_points_count_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/count-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — exact=true is trusted to be
#            filter-aware; the degenerate faces [contradictory must+must_not,
#            has_id subset, should-union] are where an approximate or
#            filter-ignoring implementation would silently diverge)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 filter-arithmetic x qdrant_behavioral_points_count_001 —
  "exact=true returns the exact number of points matching the filter" is
  verified through six filter faces whose expected counts are ALL derived
  arithmetically from the seed set (R33 lesson: count-face expectations must
  be arithmetic-derived with id-collision analysis — fresh uuid-tagged
  collection, prefix-unique ids 1..12, so no pre-existing id can collide):
  seed: ids 1..8 payload city=berlin, ids 9..12 payload city=paris.
    F1 must [match city=berlin]            -> 8   (BERLIN_N)
    F2 must [match city=paris]             -> 4   (N_SEED - BERLIN_N)
    F3 should [berlin, paris]              -> 12  (union: BERLIN_N + PARIS_N)
    F4 must_not [berlin]                   -> 4   (N_SEED - BERLIN_N)
    F5 must [berlin] + must_not [berlin]   -> 0   (contradiction: intersection
                                                   of a set and its complement)
    F6 must [has_id [1, 2, 3, 9]]          -> 3   (ids 1,2,3 in seed; all exist)
    F7 cross-face (points+scroll with F1's filter, limit 20) -> EXACTLY the
       8 berlin ids; the count face and the scroll face must agree on 8.
       (scroll is the filter-scoped read face per contract parameters
       filter+limit; points+get requires ids and carries no filter — fixed
       per D3b preverify request_required_missing.)
  [chunk_points+count coverage: strategy1 filter-arithmetic x
  qdrant_behavioral_points_count_001 (this script; positive baseline faces in
  boundary_points_count_all_001, filter type-confusion faces in
  boundary_points_count_filter_type_003, min_should branch faces in
  boundary_points_count_min_should_004, exact type-confusion faces in
  boundary_points_count_exact_type_005, malformed-body faces in
  boundary_points_count_malformed_006)]
Oracle: every count face -> 200 with result.count == the arithmetic-derived
  expectation (8/4/12/4/0/3); 200 with any other count =
  Type4_StateLogicViolation (exact count broken); 4xx on a valid filter face
  = Type1_IllegalSuccess (promise: HTTP 200 with {count}); 5xx with
  /healthz alive = Type3_RuntimeFailure; F7 -> 200 with exactly the 8 berlin
  ids in result.points[].id (set equality), else Type4 cross-face
  disagreement; transport failure -> /healthz liveness re-check then
  SCRIPT_ERROR (constraint qdrant_behavioral_points_count_001).
Constraint: qdrant_behavioral_points_count_001 (bare id) — "exact=true
  (default) performs an exact count (slower); an omitted filter counts all
  points" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+count         -> POST /collections/{collection_name}/points/count
  points+scroll        -> POST /collections/{collection_name}/points/scroll
  collections+create   -> PUT  /collections/{collection_name}
  collections+delete   -> DELETE /collections/{collection_name}
  points+upsert        -> PUT  /collections/{collection_name}/points
  healthz              -> GET  /healthz
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
BERLIN_N = 8
PARIS_N = 4  # BERLIN_N + PARIS_N == N_SEED
V = [0.1, 0.2, 0.3, 0.4]
BERLIN_IDS = list(range(1, BERLIN_N + 1))


def safe_request(method, endpoint, json=None, timeout=60, params=None):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text); transport failure -> (-1, err, err).
    Query params (wait/ordering/timeout) via params= — never stuffed into the body.
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
    """Inline liveness probe on the lightweight healthz face."""
    hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
    return hs == 200, hs, str(hraw)[:200]


def transport_dead(where):
    """Transport-branch liveness re-check (lightweight healthz face only)."""
    alive, hs, hraw = healthz_alive()
    print(f"transport failure on {where} (healthz status={hs}: {hraw})")
    print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
    return False


def match_cond(field, value):
    """FieldCondition from the contract Condition type: {key, match:{value}}."""
    return {"key": field, "match": {"value": value}}


BERLIN_COND = match_cond("city", "berlin")
PARIS_COND = match_cond("city", "paris")

# (label, filter dict, arithmetic-derived expected count)
FACES = [
    ("F1 must [city=berlin]", {"must": [BERLIN_COND]}, BERLIN_N),
    ("F2 must [city=paris]", {"must": [PARIS_COND]}, N_SEED - BERLIN_N),
    ("F3 should [berlin, paris] (union)",
     {"should": [BERLIN_COND, PARIS_COND]}, BERLIN_N + PARIS_N),
    ("F4 must_not [berlin]", {"must_not": [BERLIN_COND]}, N_SEED - BERLIN_N),
    ("F5 must [berlin] + must_not [berlin] (contradiction)",
     {"must": [BERLIN_COND], "must_not": [BERLIN_COND]}, 0),
    ("F6 must [has_id [1,2,3,9]]",
     {"must": [{"has_id": [1, 2, 3, 9]}]}, 3),
]

coll = ""


def main():
    global coll
    tag = uuid.uuid4().hex[:8]
    coll = "bpcF2" + tag

    # Arrange: own collection + seed set (wait=true => durable before counting)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    points = []
    for i in range(1, N_SEED + 1):
        city = "berlin" if i <= BERLIN_N else "paris"
        points.append({"id": i, "vector": V, "payload": {"city": city}})
    s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                             json={"points": points}, params={"wait": "true"}, timeout=120)
    if s not in (200, 201):
        print(f"setup upsert failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        # Baseline guard: omitted filter must report the full seed set before any
        # filter face is trusted (arithmetic anchor of this script)
        s, body, raw = safe_request("POST", f"/collections/{coll}/points/count",
                                    json={}, timeout=60)
        if s == -1:
            transport_dead("baseline count")
            return
        base_count = None
        if s == 200 and isinstance(body, dict) and isinstance(body.get("result"), dict):
            base_count = body["result"].get("count")
        if base_count != N_SEED:
            print(f"baseline count (omitted filter) = {base_count}, expected "
                  f"{N_SEED} — seed set not exactly visible, no defect conclusion")
            print("VERDICT: SCRIPT_ERROR — setup baseline mismatch")
            return
        print(f"baseline: omitted filter count == {N_SEED} (arithmetic anchor OK)")

        # Act + Assert: every filter face against its arithmetic-derived expectation
        for label, filt, expected in FACES:
            s, body, raw = safe_request("POST", f"/collections/{coll}/points/count",
                                        json={"filter": filt, "exact": True}, timeout=60)
            print(f"\n{label} -> status={s}")
            print(f"raw: {raw[:400]}")
            if s == -1:
                transport_dead(label)
                return
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {label}: "
                          f"exact count on a valid filter returned {s}: {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return
            if not (200 <= s <= 299):
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: "
                      f"valid filter count rejected with {s} (promise: HTTP 200 "
                      f"with count): {raw[:300]}")
                return
            result = body.get("result") if isinstance(body, dict) else None
            got = result.get("count") if isinstance(result, dict) else None
            if not (isinstance(got, int) and not isinstance(got, bool)):
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: "
                      f"result.count not an integer: {raw[:300]}")
                return
            if got != expected:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — {label}: "
                      f"exact=true count expected {expected} (arithmetic-derived "
                      f"from seed set), got {got}: {raw[:300]}")
                return
            print(f"{label}: count == {got} == expected {expected}")

        # F7 cross-face: points+scroll with F1's filter must agree on 8 ids
        # (scroll carries filter+limit per contract parameters; points+get is
        # ids-scoped and has no filter member — see request_required_paths)
        s7, b7, raw7 = safe_request("POST", f"/collections/{coll}/points/scroll",
                                    json={"filter": {"must": [BERLIN_COND]},
                                          "limit": 20, "with_payload": False,
                                          "with_vector": False}, timeout=60)
        print(f"\nF7 points+scroll (berlin filter) -> status={s7}")
        print(f"raw: {raw7[:400]}")
        if s7 == -1:
            transport_dead("F7 scroll cross-face")
            return
        if 500 <= s7 <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — F7: scroll "
                      f"cross-face returned {s7}: {raw7[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — F7 5xx and healthz down")
            return
        if not (200 <= s7 <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F7: valid "
                  f"filtered scroll rejected with {s7}: {raw7[:300]}")
            return
        result7 = b7.get("result") if isinstance(b7, dict) else None
        pts7 = result7.get("points") if isinstance(result7, dict) else None
        if not isinstance(pts7, list):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — F7: scroll "
                  f"result.points not an array (response_shape result.points): "
                  f"{raw7[:300]}")
            return
        got_ids = set()
        for p in pts7:
            if isinstance(p, dict):
                got_ids.add(p.get("id"))
        if got_ids != set(BERLIN_IDS):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F7: count "
                  f"face says {BERLIN_N} for city=berlin but scroll face "
                  f"returns {len(got_ids)} ids "
                  f"(got={sorted(got_ids)}) — cross-face disagreement: "
                  f"{raw7[:300]}")
            return
        print(f"F7: scroll id set == {BERLIN_N} berlin ids (count/scroll faces agree)")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
