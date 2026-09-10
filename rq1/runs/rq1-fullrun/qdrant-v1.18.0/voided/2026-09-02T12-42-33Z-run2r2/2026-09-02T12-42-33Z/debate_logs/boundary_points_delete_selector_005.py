#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_delete_selector_005
# strategy: strategy1 boundary-value attack on the selector grammar itself
#           (BS-04 empty/ambiguous/degenerate selector faces; the points+delete
#           request is a filter-or-ids oneOf selector per contract parameters
#           points/filter)
# endpoint: points+delete
# constraint_ids: qdrant_behavioral_points_delete_001
#                 qdrant_state_points_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/delete-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — the filter-or-ids selector
#            grammar is trusted at its degenerate boundaries: no selector at
#            all, both selectors at once, and the empty id list)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 selector-boundary x qdrant_behavioral_points_delete_001 —
  the points+delete request grammar is a filter-or-ids selector (contract
  parameters: points = "PointIdsList: delete by explicit ids", filter =
  "FilterSelector: delete by filter"; exactly one branch selects). The three
  degenerate selector boundaries, each with an exact-count state guard:
    G  guard: valid ids-delete [1] on seed 1..5 -> 200, count 4
       (proves the endpoint path live before any rejection is trusted)
    S1 body {} — NO selector at all (zero of the oneOf branches satisfied)
       -> 400/422 expected; 2xx = a delete with no target accepted (Type1)
    S2 body {"points":[2], "filter": must[grp=red]} — BOTH selectors at once
       (ambiguous) -> 400/422 expected; 2xx = ambiguous selector silently
       resolved (Type1) and the count guard reveals WHICH branch won (4->3
       points-branch / 4->3 filter-branch targets id 3 / 4->2 both applied =
       Type4 addendum)
    S3 body {"points": []} — empty id list, the degenerate boundary of the
       idempotence promise qdrant_state_points_delete_001 ("delete of
       non-existent point ids returns success"; an empty list vacuously
       contains only non-existent ids) -> EITHER 200 no-op with count
       unchanged at 4 (consistent with the promise) OR 400/422 (explicit
       rejection of the degenerate selector) — both non-defect dispositions,
       recorded for the G9 cross-face consistency ledger; 5xx = Type3;
       200 WITH count change = Type4 (empty list deleted something)
  [chunk_points+delete coverage: strategy1 selector-boundary faces x
  qdrant_behavioral_points_delete_001 + qdrant_state_points_delete_001
  (this script; idempotence faces in boundary_points_delete_idempotent_001,
  filter-wipe faces in boundary_points_delete_filter_wipe_002, 404 leg in
  boundary_points_delete_404_003, invalid-filter 400 leg in
  boundary_points_delete_invalid_filter_004, cross-face invisibility in
  boundary_points_delete_invisibility_006)]
Oracle: S1/S2 -> 400/422 clean rejection (any 2xx = Type1_IllegalSuccess:
  selector-less/ambiguous delete accepted; S2 2xx with count 2 = Type4
  addendum — both branches applied; 5xx with /healthz alive =
  Type3_RuntimeFailure); S3 -> 200 with count == 4 OR 400/422 (both valid
  dispositions; 5xx = Type3; 200 with count != 4 = Type4_StateLogicViolation);
  G -> 200 with count == 4 (other = Type4; non-200 = Type1); transport
  failure -> /healthz liveness re-check then SCRIPT_ERROR
  (constraints qdrant_behavioral_points_delete_001,
  qdrant_state_points_delete_001).
Constraint: qdrant_behavioral_points_delete_001 (bare id) — "returns 200 ok
  (UpdateResult) on success; 404 when the collection is missing; 400 on an
  invalid filter" (evidence_tier: explicit; level: endpoint);
  qdrant_state_points_delete_001 (bare id) — "delete of non-existent point
  ids returns success (idempotent)" (evidence_tier: explicit; level: system)

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
N_SEED = 5
V = [0.1, 0.2, 0.3, 0.4]
GUARD_BASELINE = N_SEED - 1  # 4

# S2's two branches target DIFFERENT points so the count guard identifies the winner:
# points-branch consumes id 2 (grp=a), filter-branch consumes id 3 (grp=red).
S2_BODY = {"points": [2], "filter": {"must": [{"key": "grp", "match": {"value": "red"}}]}}


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


def delete_raw(coll, body):
    """points+delete face with an arbitrary raw body, wait=true (query param)."""
    return safe_request("POST", f"/collections/{coll}/points/delete",
                        json=body, timeout=60, params={"wait": "true"})


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpd5s" + tag

    # Arrange: own collection + seed ids 1..5 (id3=red, others a/b)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        points = []
        for i in range(1, N_SEED + 1):
            grp = "red" if i == 3 else ("a" if i <= 2 else "b")
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
        print(f"seed baseline: exact count == {N_SEED}")

        # ---- G: guard — valid ids-delete -> 200, count 4 ----
        sg, _, rawg = delete_raw(coll, {"points": [1]})
        print(f"\nG guard valid ids-delete [1] -> status={sg}")
        print(f"raw: {rawg[:400]}")
        if sg == -1:
            transport_dead("G guard")
            return
        if 500 <= sg <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — G: valid delete returned {sg}: {rawg[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — G 5xx and healthz down")
            return
        if not (200 <= sg <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — G: valid delete rejected with {sg} (promise: HTTP 200): {rawg[:300]}")
            return
        cnt, cs, craw = exact_count(coll)
        if cnt != GUARD_BASELINE:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — G: count expected {GUARD_BASELINE}, got {cnt}: {str(craw)[:300]}")
            return
        print(f"G: 200, count == {cnt} == {GUARD_BASELINE} (guard baseline set)")

        # ---- S1: selector-less body {} ----
        s1, _, raw1 = delete_raw(coll, {})
        print(f"\nS1 selector-less body {{}} -> status={s1}")
        print(f"raw: {raw1[:400]}")
        if s1 == -1:
            transport_dead("S1")
            return
        if 500 <= s1 <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — S1: selector-less body returned {s1}: {raw1[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — S1 5xx and healthz down")
            return
        if 200 <= s1 <= 299:
            cnt, cs, craw = exact_count(coll)
            blast = ("count unchanged (silent no-op)"
                     if cnt == GUARD_BASELINE else
                     f"DESTRUCTIVE: count moved {GUARD_BASELINE} -> {cnt}")
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — S1: delete with "
                  f"NO selector accepted with status {s1} (the filter-or-ids oneOf "
                  f"is satisfied by zero branches); blast radius: {blast}: {raw1[:300]}")
            if cnt != GUARD_BASELINE:
                print("addendum: state mutated by a target-less delete — Type4_StateLogicViolation")
            return
        if s1 in (400, 422):
            print("S1: 400/422 clean rejection (no selector = invalid request)")
        else:
            print(f"NOTE: S1 returned {s1} (neither 2xx nor 400/422); recorded for the judge")

        # ---- S2: BOTH selectors at once ----
        s2, _, raw2 = delete_raw(coll, S2_BODY)
        print(f"\nS2 both selectors (points [2] AND filter grp=red) -> status={s2}")
        print(f"raw: {raw2[:400]}")
        if s2 == -1:
            transport_dead("S2")
            return
        if 500 <= s2 <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — S2: ambiguous selector returned {s2}: {raw2[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — S2 5xx and healthz down")
            return
        if 200 <= s2 <= 299:
            cnt, cs, craw = exact_count(coll)
            if cnt == GUARD_BASELINE - 2:
                how = "BOTH branches applied (2 points consumed) — Type4_StateLogicViolation addendum"
            elif cnt == GUARD_BASELINE - 1:
                how = ("ONE branch silently resolved the ambiguity "
                       f"(count {GUARD_BASELINE} -> {cnt})")
            else:
                how = f"UNCLASSIFIED state change (count {GUARD_BASELINE} -> {cnt})"
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — S2: ambiguous "
                  f"selector (points AND filter simultaneously) accepted with "
                  f"status {s2}; resolution: {how}: {raw2[:300]}")
            if cnt == GUARD_BASELINE - 2:
                print("addendum: both selector branches fired on one request — Type4_StateLogicViolation")
            return
        if s2 in (400, 422):
            print("S2: 400/422 clean rejection (ambiguous selector = invalid request)")
        else:
            print(f"NOTE: S2 returned {s2} (neither 2xx nor 400/422); recorded for the judge")

        # ---- S3: empty id list (degenerate idempotence boundary) ----
        s3, _, raw3 = delete_raw(coll, {"points": []})
        print(f"\nS3 empty id list {{\"points\": []}} -> status={s3}")
        print(f"raw: {raw3[:400]}")
        if s3 == -1:
            transport_dead("S3")
            return
        if 500 <= s3 <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — S3: empty id list returned {s3}: {raw3[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — S3 5xx and healthz down")
            return
        if 200 <= s3 <= 299:
            cnt, cs, craw = exact_count(coll)
            if cnt != GUARD_BASELINE:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — S3: "
                      f"empty id list returned 200 AND moved the count "
                      f"{GUARD_BASELINE} -> {cnt} (an empty list deleted "
                      f"something): {str(craw)[:300]}")
                return
            print(f"S3: 200 no-op with count unchanged at {GUARD_BASELINE} — "
                  f"consistent with the idempotence promise (empty list "
                  f"vacuously contains only non-existent ids)")
        elif s3 in (400, 422):
            print("S3: 400/422 explicit rejection of the degenerate selector — "
                  "recorded disposition (contract pins no expectation for the "
                  "empty-list boundary; non-defect per G5)")
        else:
            print(f"NOTE: S3 returned {s3} (neither 2xx nor 400/422); recorded for the judge")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
