#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_delete_invalid_filter_004
# strategy: strategy2 type-boundary attack (invalid-filter 400 leg of the
#           200/404/400 endpoint promise; BS-01 clause-type confusion faces,
#           each with a state guard separating silent no-op from wipe)
# endpoint: points+delete
# constraint_ids: qdrant_behavioral_points_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/delete-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — the Filter type declares
#            should/must/must_not as clause ARRAYS and each FieldCondition as
#            {key, match}; serde coercion gaps could let string/object/int
#            clause values or null matches through with 200 and undefined
#            delete semantics)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-confusion x qdrant_behavioral_points_delete_001 — the
  "400 on an invalid filter" leg is attacked with five type-confused Filter
  bodies (contract Filter type: {should?, min_should?, must?, must_not?} with
  clause arrays of Condition {key, match}); every face runs against seeded
  data with an exact-count state guard so a silently-accepted invalid filter
  is classified by its blast radius (no-op vs destructive wipe):
    G  guard: VALID filter delete (must[grp=red] on 3 red of 9 seeded)
       -> 200, count 6 — proves the collection/grammar path is live before
       any 400 is trusted (G4 positive pairing)
    T1 {"filter": {"must": "berlin"}}            clause list as STRING
    T2 {"filter": {"must_not": {"key":"city"}}}  clause list as OBJECT
    T3 {"filter": {"should": 42}}                clause list as INT
    T4 {"filter": {"must": [{"key":"grp","match": null}]}}  match = null
    T5 {"filter": {"must": [{"match": {"value":"x"}}]}}     key missing
  Each invalid face: expected 400/422 clean rejection. 2xx = invalid filter
  accepted (Type1_IllegalSuccess); if additionally the count moved, the
  acceptance was DESTRUCTIVE (Type4 addendum). 5xx = Type3. Rejection text
  scanned for filter-family tokens (strategy 5 diagnostics note for the judge,
  not a standalone defect per session convention).
  [chunk_points+delete coverage: strategy2 invalid-filter 400 leg x
  qdrant_behavioral_points_delete_001 (this script; idempotence faces in
  boundary_points_delete_idempotent_001, filter-wipe faces in
  boundary_points_delete_filter_wipe_002, 404 leg in
  boundary_points_delete_404_003, selector-boundary faces in
  boundary_points_delete_selector_005, cross-face invisibility in
  boundary_points_delete_invisibility_006)]
Oracle: T1..T5 -> 400/422 clean rejection (any 2xx =
  Type1_IllegalSuccess: invalid filter accepted; 2xx WITH count change from
  the guard baseline 6 = Type4_StateLogicViolation addendum — destructive
  acceptance; 5xx with /healthz alive = Type3_RuntimeFailure); G -> 200 with
  exact count == 6 (other = Type4; non-200 = Type1 valid filter delete
  rejected); transport failure -> /healthz liveness re-check then SCRIPT_ERROR
  (constraint qdrant_behavioral_points_delete_001).
Constraint: qdrant_behavioral_points_delete_001 (bare id) — "returns 200 ok
  (UpdateResult) on success; 404 when the collection is missing; 400 on an
  invalid filter" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+delete         -> POST /collections/{collection_name}/points/delete
  points+count          -> POST /collections/{collection_name}/points/count
  collections+create    -> PUT  /collections/{collection_name}
  collections+delete    -> DELETE /collections/{collection_name}
  points+upsert         -> PUT  /collections/{collection_name}/points
  healthz               -> GET  /healthz
  (wait is a query parameter on the delete/upsert faces — passed via params=)
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
V = [0.1, 0.2, 0.3, 0.4]
GUARD_BASELINE = N_SEED - RED_N  # 6

# (label, invalid filter body, filter-family tokens expected in diagnostics)
FACES = [
    ("T1 must as STRING",
     {"must": "berlin"}),
    ("T2 must_not as OBJECT",
     {"must_not": {"key": "grp"}}),
    ("T3 should as INT",
     {"should": 42}),
    ("T4 match null",
     {"must": [{"key": "grp", "match": None}]}),
    ("T5 key missing",
     {"must": [{"match": {"value": "x"}}]}),
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


def exact_count(coll):
    """Exact count via the points+count face (result.count integer per shape)."""
    s, body, raw = safe_request("POST", f"/collections/{coll}/points/count",
                                json={"exact": True}, timeout=60)
    if s == -1 or not (200 <= s <= 299):
        return None, s, raw
    result = body.get("result") if isinstance(body, dict) else None
    got = result.get("count") if isinstance(result, dict) else None
    return got, s, raw


def delete_body(coll, body):
    """points+delete face with an arbitrary selector body, wait=true (query param)."""
    return safe_request("POST", f"/collections/{coll}/points/delete",
                        json=body, timeout=60, params={"wait": "true"})


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpd4t" + tag

    # Arrange: own collection + seed set (3 red / 6 blue)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        points = []
        for i in range(1, N_SEED + 1):
            grp = "red" if i <= RED_N else "blue"
            points.append({"id": i, "vector": V, "payload": {"grp": grp}})
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": points}, params={"wait": "true"}, timeout=120)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return
        cnt, cs, craw = exact_count(coll)
        if cnt != N_SEED:
            print(f"seed count = {cnt} (status={cs}), expected {N_SEED}: {str(craw)[:200]}")
            print("VERDICT: SCRIPT_ERROR — setup baseline mismatch")
            return
        print(f"seed baseline: exact count == {N_SEED} ({RED_N} red + {N_SEED - RED_N} blue)")

        # ---- G: guard — VALID filter delete (must[grp=red]) -> 200, count 6 ----
        gbody = {"filter": {"must": [{"key": "grp", "match": {"value": "red"}}]}}
        sg, _, rawg = delete_body(coll, gbody)
        print(f"\nG guard valid filter delete must[grp=red] -> status={sg}")
        print(f"raw: {rawg[:400]}")
        if sg == -1:
            transport_dead("G guard")
            return
        if 500 <= sg <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — G: valid filter delete returned {sg}: {rawg[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — G 5xx and healthz down")
            return
        if not (200 <= sg <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — G: valid filter "
                  f"delete rejected with {sg} (promise: HTTP 200): {rawg[:300]}")
            return
        cnt, cs, craw = exact_count(coll)
        if cnt != GUARD_BASELINE:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — G: count "
                  f"expected {GUARD_BASELINE} ({N_SEED} - {RED_N} red), got {cnt}: {str(craw)[:300]}")
            return
        print(f"G: 200, count == {cnt} == {GUARD_BASELINE} (guard baseline set)")

        # ---- T1..T5: invalid filter faces ----
        for label, filt in FACES:
            body = {"filter": filt}
            s, _, raw = delete_body(coll, body)
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
                    print("VERDICT: SCRIPT_ERROR — {l} 5xx and healthz down".format(l=label))
                return
            if 200 <= s <= 299:
                cnt, cs, craw = exact_count(coll)
                blast = ("count unchanged (silent no-op acceptance)"
                         if cnt == GUARD_BASELINE else
                         f"DESTRUCTIVE: count moved {GUARD_BASELINE} -> {cnt}")
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: "
                      f"invalid filter ACCEPTED with status {s} (promise: 400); "
                      f"blast radius: {blast}: {raw[:300]}")
                if cnt != GUARD_BASELINE:
                    print("addendum: the acceptance was destructive — "
                          "Type4_StateLogicViolation (invalid input mutated state)")
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

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
