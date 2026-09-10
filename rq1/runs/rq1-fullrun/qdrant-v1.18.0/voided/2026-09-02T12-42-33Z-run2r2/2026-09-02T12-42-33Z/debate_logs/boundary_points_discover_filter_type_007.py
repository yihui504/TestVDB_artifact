#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_discover_filter_type_007
# strategy: strategy2 type-boundary attack on the Filter parameter (the
#           filter-family mirror of the R34/R35 grammar on the READ-ONLY
#           discover face; BS-01 clause-type confusion faces, each with an
#           arithmetic-derived result-set oracle and an exact-count
#           non-destructiveness guard)
# endpoint: points+discover
# constraint_ids: qdrant_behavioral_points_discover_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/explore/discover-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — the Filter type declares
#            should/must/must_not as clause ARRAYS and each FieldCondition as
#            {key, match}; the R35 round measured this grammar accepted
#            DESTRUCTIVELY on points+delete (matcher-less conditions), while
#            R34 measured points+count rejecting it — this script records the
#            READ-ONLY discover member of the same family: acceptance here is
#            non-destructive Type1, and the cross-face disposition
#            consistency (G9) is the adjudication frame)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 filter-type x qdrant_behavioral_points_discover_001 — the
  discover request's filter parameter (contract parameter spec: Filter
  {should?, min_should?, must?, must_not?}) is attacked with the same five
  type-confused faces measured on the delete family in R35, on a live sparse
  seeded collection (9 points, 3 red / 6 blue):
    G  guard: VALID filter must[grp=red] + sparse target + using="text" +
       with_payload=true, limit=9 -> 200, result array with 1..3 elements
       and EVERY result payload grp=="red" (arithmetic-derived: the filter
       admits at most the 3 seeded red points) — proves the filter path
       live and semantics-correct before any 400 is trusted (G4 pairing).
    T1 {"filter": {"must": "red"}}                    clause list as STRING
    T2 {"filter": {"must_not": {"key": "grp"}}}       clause list as OBJECT
    T3 {"filter": {"should": 42}}                     clause list as INT
    T4 {"filter": {"must": [{"key":"grp","match": null}]}}  match = null
    T5 {"filter": {"must": [{"match": {"value":"red"}}]}}   key missing
  Each invalid face: expected 400/422 clean rejection. 2xx = invalid filter
  accepted (Type1_IllegalSuccess). R35 family frame: unlike delete (where
  the same acceptance wiped data), this face is READ-ONLY, so the acceptance
  is non-destructive by construction — certified by an exact count == 9
  before/after; the cross-face disposition (count R34 NOT / delete R35
  DEFECT / discover = read-only member) is recorded for the G9 judge.
  5xx = Type3. Rejection text scanned for filter-family tokens (strategy 5
  diagnostics note for the judge, not a standalone defect per session
  convention).
  [chunk_points+discover coverage: strategy2 filter family mirror x
  qdrant_behavioral_points_discover_001 (this script; positive/shape in
  boundary_points_discover_positive_001, context type-confusion in
  boundary_points_discover_context_type_002, 404 leg in
  boundary_points_discover_404_003, limit matrix in
  boundary_points_discover_limit_004, presence matrix in
  boundary_points_discover_presence_005, sparse-target shape in
  boundary_points_discover_sparse_target_006, malformed stream in
  boundary_points_discover_malformed_008)]
Oracle: G -> 200 with result array of 1..3 elements all carrying
  payload.grp=="red" (other length = Type4; any non-red result =
  Type4_StateLogicViolation; non-200 = valid filtered discover rejected,
  Type1 convention per session); T1..T5 -> 400/422 clean rejection (any
  2xx = Type1_IllegalSuccess: invalid filter accepted — non-destructive
  read-only face, count stays 9; 5xx with /healthz alive =
  Type3_RuntimeFailure); transport failure -> /healthz liveness re-check
  then SCRIPT_ERROR (constraint qdrant_behavioral_points_discover_001).
Constraint: qdrant_behavioral_points_discover_001 (bare id) — "returns 200
  [ScoredPoint]; 400 on invalid context/pairs; 404 for a missing collection"
  (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+discover       -> POST /collections/{collection_name}/points/discover
  points+count          -> POST /collections/{collection_name}/points/count
  collections+create    -> PUT  /collections/{collection_name}
  collections+delete    -> DELETE /collections/{collection_name}
  points+upsert         -> PUT  /collections/{collection_name}/points
  healthz               -> GET  /healthz
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
N_SEED = 9
RED_N = 3
SPARSE_NAME = "text"
DENSE_NAME = "dense"
GUARD_TARGET = {"indices": [1, 2, 3], "values": [1.0, 1.0, 1.0]}
GUARD_CONTEXT = [{"positive": 1, "negative": 4}]
VALID_FILTER = {"must": [{"key": "grp", "match": {"value": "red"}}]}

# (label, invalid filter body, filter-family tokens expected in diagnostics)
FACES = [
    ("T1 must as STRING",
     {"must": "red"}),
    ("T2 must_not as OBJECT",
     {"must_not": {"key": "grp"}}),
    ("T3 should as INT",
     {"should": 42}),
    ("T4 match null",
     {"must": [{"key": "grp", "match": None}]}),
    ("T5 key missing",
     {"must": [{"match": {"value": "red"}}]}),
]


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


def sparse_vec(i):
    """Sparse vector per cluster: red over indices 1..3, blue over 4..6."""
    if i <= RED_N:
        return {"indices": [1, 2, 3], "values": [round(0.9 + 0.02 * i, 3), 0.8, 0.7]}
    return {"indices": [4, 5, 6], "values": [round(0.9 - 0.01 * i, 3), 0.85, 0.6]}


def dense_vec(i):
    """Dense vector per cluster (Cosine; absolute scores are never asserted)."""
    base = 0.1 if i <= RED_N else 0.9
    return [round(base + 0.001 * i, 4)] * DIM


def setup(coll):
    """Own collection: named dense vector + named sparse vector + 9 points."""
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {DENSE_NAME: {"size": DIM, "distance": "Cosine"}},
                                   "sparse_vectors": {SPARSE_NAME: {}}}, timeout=60)
    if s not in (200, 201):
        return False, raw
    pts = []
    for i in range(1, N_SEED + 1):
        pts.append({"id": i,
                    "vector": {DENSE_NAME: dense_vec(i), SPARSE_NAME: sparse_vec(i)},
                    "payload": {"grp": "red" if i <= RED_N else "blue"}})
    s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                             json={"points": pts}, params={"wait": "true"}, timeout=120)
    if s not in (200, 201):
        return False, raw
    return True, ""


def discover(coll, body):
    """points+discover face."""
    return safe_request("POST", f"/collections/{coll}/points/discover",
                        json=body, timeout=60)


def exact_count(coll):
    """Exact count via the points+count face (result.count integer per shape)."""
    s, body, raw = safe_request("POST", f"/collections/{coll}/points/count",
                                json={"exact": True}, timeout=60)
    if s == -1 or not (200 <= s <= 299):
        return None, s, raw
    result = body.get("result") if isinstance(body, dict) else None
    got = result.get("count") if isinstance(result, dict) else None
    return got, s, raw


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpdw7" + tag

    ok, raw = setup(coll)
    if not ok:
        print(f"setup failed: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        cnt, cs, craw = exact_count(coll)
        if cnt != N_SEED:
            print(f"seed count = {cnt} (status={cs}), expected {N_SEED}: {str(craw)[:200]}")
            print("VERDICT: SCRIPT_ERROR — setup baseline mismatch")
            return
        print(f"seed baseline: exact count == {N_SEED} ({RED_N} red + {N_SEED - RED_N} blue)")

        # ---- G: guard — VALID filtered discover (must[grp=red]) ----
        gbody = {"using": SPARSE_NAME, "target": GUARD_TARGET,
                 "context": GUARD_CONTEXT, "filter": VALID_FILTER,
                 "limit": 9, "with_payload": True}
        s, body, raw = discover(coll, gbody)
        print(f"\nG guard valid filtered discover must[grp=red] -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            transport_dead("G guard")
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — G: valid "
                      f"filtered discover returned {s}: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — G 5xx and healthz down")
            return
        if not (200 <= s <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — G: valid "
                  f"filtered discover rejected with {s} (promise: HTTP 200): "
                  f"{raw[:300]}")
            return
        res = body.get("result") if isinstance(body, dict) else None
        if not isinstance(res, list) or not (1 <= len(res) <= RED_N):
            got = len(res) if isinstance(res, list) else "non-array"
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — G: 200 "
                  f"but filtered result {got} outside [1, {RED_N}] (filter "
                  f"admits at most the {RED_N} seeded red points): {raw[:300]}")
            return
        non_red = []
        for p in res:
            payload = p.get("payload") if isinstance(p, dict) else None
            grp = payload.get("grp") if isinstance(payload, dict) else None
            if grp != "red":
                non_red.append(p.get("id"))
        if non_red:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — G: "
                  f"filtered discover returned non-red ids {non_red} through "
                  f"must[grp=red]: {raw[:300]}")
            return
        print(f"G: 200, {len(res)} result(s), all grp=red (guard baseline set)")

        # ---- T1..T5: invalid filter faces on the read-only discover face ----
        for label, filt in FACES:
            body_ = {"using": SPARSE_NAME, "target": GUARD_TARGET,
                     "context": GUARD_CONTEXT, "filter": filt, "limit": 3}
            s, _, raw = discover(coll, body_)
            print(f"\n{label} -> status={s}")
            print(f"raw: {raw[:400]}")
            if s == -1:
                transport_dead(label)
                return
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {label}: "
                          f"invalid filter crashed the endpoint with {s}: {raw[:300]}")
                else:
                    print(f"VERDICT: SCRIPT_ERROR — {label} 5xx and healthz down")
                return
            if 200 <= s <= 299:
                cnt2, _, _ = exact_count(coll)
                blast = ("substrate untouched — non-destructive acceptance, "
                         "as expected for the read-only face"
                         if cnt2 == N_SEED else
                         f"UNEXPECTED state change: count {N_SEED} -> {cnt2}")
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: "
                      f"invalid filter ACCEPTED with status {s} (promise: 400); "
                      f"R35 family frame: read-only face so non-destructive; "
                      f"count guard: {blast}: {raw[:300]}")
                return
            if s in (400, 422):
                low = raw.lower()
                named = any(t in low for t in ("filter", "must", "should", "condition", "clause", "match"))
                note = ("diagnostics name the filter construct"
                        if named else
                        "NOTE (strategy5): rejection text names no filter-family "
                        "token — diagnostics gap recorded for the judge")
                print(f"{label}: {s} clean rejection; {note}")
            else:
                print(f"NOTE: {label} returned {s} (neither 2xx nor 400/422); "
                      f"recorded for the judge — unexpected rejection class")

        print("cross-face disposition note (G9): filter grammar family — "
              "count R34 rejected / delete R35 accepted-destructively / "
              "discover this round read-only member")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
