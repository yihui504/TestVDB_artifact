#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_count_filter_type_003
# strategy: strategy2 type-boundary attack (Filter parameter type confusion
#           on the count face)
# endpoint: points+count
# constraint_ids: qdrant_behavioral_points_count_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/count-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — serde is trusted to
#            validate the nested Filter structure; wrong-shape filters
#            (string/array/object-for-array/null-clause) are where silent
#            coercion leaks through with 200 and an undefined count)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-confusion x qdrant_behavioral_points_count_001 —
  the promise "an omitted filter counts all points; exact=true returns the
  exact number matching the filter" presupposes the Filter parameter
  (type Filter = {should?, min_should?, must?, must_not?} per contract
  data_types) is type-checked. Faces on a LIVE 12-point collection
  (8 berlin / 4 paris, fresh uuid-tagged, no id collisions):
    F1 filter=null — threat_model by-design note says null may mean
       no-filter; adjudicated as CONSISTENT DISPOSITION (G9): 200 with
       count == 12 (same as omitted) is clean; 400/422 is recorded as NOTE
       (asymmetric but defensible strictness); 200 with count != 12 =
       Type4; 5xx = Type3.
    F2 filter={} (legal empty Filter — all clauses optional) — 200 with
       count == 12; anything else is a violation.
    F3 filter="berlin" (string for object) — must be 400/422; 2xx = Type1.
    F4 filter=[{...berlin cond...}] (array for object) — must be 400/422;
       2xx = Type1.
    F5 filter={"must": {...berlin cond...}} (object for conditions ARRAY)
       — must be 400/422; 2xx = Type1 (even if coerced to the "right"
       answer 8 — wrong type accepted is the defect).
    F6 filter={"should": null} (null clause, BS-01 'filter with null
       conditions') — clean: 200 with count == 12 (null clause = absent) or
       400/422 (NOTE); 200 with count != 12 = Type4; 5xx = Type3.
  [chunk_points+count coverage: strategy2 type-confusion x filter x
  qdrant_behavioral_points_count_001 (this script; min_should branch faces
  in boundary_points_count_min_should_004, exact type-confusion faces in
  boundary_points_count_exact_type_005; positive baselines in
  boundary_points_count_all_001 / boundary_points_count_filter_arith_002,
  malformed-body faces in boundary_points_count_malformed_006)]
Oracle: F3/F4/F5 -> 400/422 clean rejection; any 2xx = Type1_IllegalSuccess
  (Filter type violation silently accepted — count from an undefined filter
  shape); 5xx with /healthz alive = Type3_RuntimeFailure; F1/F2/F6 -> 200
  with result.count == 12 (the all-points count), mismatch = Type4; F2 4xx
  = Type1 (valid empty Filter rejected); transport failure -> /healthz
  liveness re-check then SCRIPT_ERROR (constraint
  qdrant_behavioral_points_count_001).
Constraint: qdrant_behavioral_points_count_001 (bare id) — "exact=true
  (default) performs an exact count (slower); an omitted filter counts all
  points" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+count         -> POST /collections/{collection_name}/points/count
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


BERLIN_COND = {"key": "city", "match": {"value": "berlin"}}

# Faces with per-face posture:
#   posture "reject"   -> 400/422 clean is the pass; 2xx = Type1
#   posture "allpts"   -> 200 count==12 is the pass; 200 other count = Type4;
#                         4xx = NOTE (defensible strictness), recorded
FACES = [
    ("F1 filter=null (null vs omitted consistency)", None, "allpts"),
    ("F2 filter={} (legal empty Filter)", {}, "allpts_strict"),
    ("F3 filter=\"berlin\" (string for object)",
     "berlin", "reject"),
    ("F4 filter=[{...}] (array for object)", [BERLIN_COND], "reject"),
    ("F5 filter={\"must\": {...}} (object for conditions array)",
     {"must": BERLIN_COND}, "reject"),
    ("F6 filter={\"should\": null} (null clause)",
     {"should": None}, "allpts"),
]

coll = ""


def main():
    global coll
    tag = uuid.uuid4().hex[:8]
    coll = "bpcT3" + tag

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
        notes = []
        for label, filt, posture in FACES:
            s, body, raw = safe_request("POST", f"/collections/{coll}/points/count",
                                        json={"filter": filt}, timeout=60)
            print(f"\n{label} -> status={s}")
            print(f"raw: {raw[:400]}")
            if s == -1:
                transport_dead(label)
                return
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {label}: "
                          f"malformed-typed filter crashed the count face with "
                          f"{s}: {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return
            if posture == "reject":
                if 200 <= s <= 299:
                    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: "
                          f"filter type violation silently accepted with {s}; the "
                          f"count then derives from an undefined filter shape: "
                          f"{raw[:300]}")
                    return
                print(f"{label}: rejected with {s} (clean)")
                continue
            # posture allpts / allpts_strict: expect 200 with the all-points count
            if not (200 <= s <= 299):
                if posture == "allpts":
                    notes.append(f"{label}: {s} (asymmetric vs omitted-filter "
                                 f"face which returns 200 — defensible strictness, "
                                 f"judge call)")
                    print(f"{label}: NOTE {s} — recorded for the judge")
                    continue
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: "
                      f"valid empty Filter rejected with {s} (data_types: all "
                      f"clauses optional): {raw[:300]}")
                return
            result = body.get("result") if isinstance(body, dict) else None
            got = result.get("count") if isinstance(result, dict) else None
            if not (isinstance(got, int) and not isinstance(got, bool)):
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: "
                      f"result.count not an integer: {raw[:300]}")
                return
            if got != N_SEED:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                      f"{label}: filter that imposes no constraint must count "
                      f"all {N_SEED} points, got {got}: {raw[:300]}")
                return
            print(f"{label}: 200 with count == {got} == N_SEED (consistent)")

        if notes:
            for n in notes:
                print(f"NOTE (judge call): {n}")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
