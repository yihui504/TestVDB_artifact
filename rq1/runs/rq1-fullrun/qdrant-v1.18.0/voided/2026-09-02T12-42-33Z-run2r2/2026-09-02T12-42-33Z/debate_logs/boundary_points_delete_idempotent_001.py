#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_delete_idempotent_001
# strategy: strategy1 boundary-value attack (idempotence promise faces with
#           arithmetic-derived survivor counts and id-collision analysis)
# endpoint: points+delete
# constraint_ids: qdrant_state_points_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/delete-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — the idempotent-DELETE promise
#            "delete of non-existent ids returns success" is trusted at its
#            degenerate boundaries: empty collection, re-delete of already
#            deleted ids, and mixed existing+non-existent id lists)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary x qdrant_state_points_delete_001 — the idempotence
  leg "delete of non-existent point ids returns success (idempotent)" is
  exercised at its four degenerate faces, with every survivor count derived
  arithmetically from the seed set (R33 lesson: count/delete expectations
  arithmetic-derived with id-collision analysis — fresh uuid-tagged
  collection, prefix-unique ids 1..6, so no pre-existing id can collide):
    I1 delete non-existent ids [101,102,103] on a FRESH EMPTY collection
       -> 200 (the promise in its purest form; threat model confirms
       idempotent 200 is by-design correct — oracle scoped accordingly)
    I2 delete existing ids [1,2] from seed 1..6       -> 200, count 6-2=4
    I3 RE-delete the SAME ids [1,2] a second time      -> 200, count stays 4
       (the idempotent repeat must not consume fresh survivors)
    I4 delete MIXED [999(non-existent), 3(existing)]  -> 200, count 4-1=3
       (a non-existent id inside a valid list must not fail the request)
  Cross-face close-out (R34 lesson: persistence judged via count+scroll
  cross-face): unfiltered scroll must return EXACTLY the survivor id set
  {4,5,6} after I4.
  [chunk_points+delete coverage: strategy1 idempotence faces x
  qdrant_state_points_delete_001 (this script; match-all filter wipe faces
  in boundary_points_delete_filter_wipe_002, 404 leg in
  boundary_points_delete_404_003, invalid-filter 400 leg in
  boundary_points_delete_invalid_filter_004, selector-boundary faces in
  boundary_points_delete_selector_005, cross-face invisibility in
  boundary_points_delete_invisibility_006)]
Oracle: I1 -> 200 (4xx on a valid non-existent-id delete = Type1_IllegalSuccess
  contradicting the promise; 5xx with /healthz alive = Type3_RuntimeFailure);
  I2/I3/I4 -> 200 each with result count face == the arithmetic-derived
  survivor count (6/4/4/3 respectively at their points in the sequence);
  I3 count != 4 = Type4_StateLogicViolation (re-delete consumed a survivor);
  I4 count != 3 = Type4 (mixed-list semantics broken); final scroll face must
  return exactly ids {4,5,6} (any leaked 1/2/3 or missing 4/5/6 = Type4
  cross-face disagreement); transport failure -> /healthz liveness re-check
  then SCRIPT_ERROR (constraint qdrant_state_points_delete_001).
Constraint: qdrant_state_points_delete_001 (bare id) — "delete of non-existent
  point ids returns success (idempotent); filter-based delete removes every
  matching point (all points when the filter matches all)"
  (evidence_tier: explicit; level: system)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+delete         -> POST /collections/{collection_name}/points/delete
  points+count          -> POST /collections/{collection_name}/points/count
  points+scroll         -> POST /collections/{collection_name}/points/scroll
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
N_SEED = 6
V = [0.1, 0.2, 0.3, 0.4]
SURVIVORS_AFTER_I4 = [4, 5, 6]


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
    if s == -1:
        return None, s, raw
    if not (200 <= s <= 299):
        return None, s, raw
    result = body.get("result") if isinstance(body, dict) else None
    got = result.get("count") if isinstance(result, dict) else None
    return got, s, raw


def delete_points(coll, ids):
    """Id-selector delete on the points+delete face, wait=true (query param)."""
    return safe_request("POST", f"/collections/{coll}/points/delete",
                        json={"points": ids}, timeout=60, params={"wait": "true"})


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpd1a" + tag

    # Arrange: own collection (uuid-tagged => no id collision with other rounds)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        # ---- I1: delete non-existent ids on a fresh EMPTY collection ----
        s1, b1, raw1 = delete_points(coll, [101, 102, 103])
        print(f"I1 delete non-existent ids on empty collection -> status={s1}")
        print(f"raw: {raw1[:400]}")
        if s1 == -1:
            transport_dead("I1")
            return
        if 500 <= s1 <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — I1: idempotent "
                      f"delete on empty collection returned {s1}: {raw1[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — I1 5xx and healthz down")
            return
        if not (200 <= s1 <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — I1: delete of "
                  f"non-existent ids rejected with {s1}; promise says idempotent "
                  f"success (threat model: idempotent 200 is by-design): {raw1[:300]}")
            return
        cnt, cs, craw = exact_count(coll)
        if cnt != 0:
            print(f"I1 post count = {cnt} (status={cs}), expected 0 on untouched "
                  f"empty collection: {str(craw)[:200]}")
            print("VERDICT: SCRIPT_ERROR — setup baseline mismatch")
            return
        print("I1: 200 idempotent success, count still 0 — promise kept")

        # ---- seed ids 1..6 ----
        points = [{"id": i, "vector": V, "payload": {"grp": "seed"}} for i in range(1, N_SEED + 1)]
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
        print(f"seed baseline: exact count == {N_SEED} (arithmetic anchor OK)")

        # ---- I2: delete existing ids [1,2] -> 200, count 4 ----
        s2, _, raw2 = delete_points(coll, [1, 2])
        print(f"\nI2 delete existing ids [1,2] -> status={s2}")
        print(f"raw: {raw2[:400]}")
        if s2 == -1:
            transport_dead("I2")
            return
        if 500 <= s2 <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — I2: valid delete returned {s2}: {raw2[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — I2 5xx and healthz down")
            return
        if not (200 <= s2 <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — I2: valid delete rejected with {s2}: {raw2[:300]}")
            return
        cnt, cs, craw = exact_count(coll)
        if cnt != N_SEED - 2:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — I2: count "
                  f"expected {N_SEED - 2} (6 seeded - 2 deleted), got {cnt}: {str(craw)[:300]}")
            return
        print(f"I2: 200, count == {cnt} == {N_SEED - 2}")

        # ---- I3: RE-delete the same ids [1,2] -> 200, count stays 4 ----
        s3, _, raw3 = delete_points(coll, [1, 2])
        print(f"\nI3 re-delete ids [1,2] (already deleted) -> status={s3}")
        print(f"raw: {raw3[:400]}")
        if s3 == -1:
            transport_dead("I3")
            return
        if 500 <= s3 <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — I3: idempotent re-delete returned {s3}: {raw3[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — I3 5xx and healthz down")
            return
        if not (200 <= s3 <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — I3: idempotent "
                  f"re-delete of already-deleted ids rejected with {s3} (promise: "
                  f"non-existent id delete is idempotent success): {raw3[:300]}")
            return
        cnt, cs, craw = exact_count(coll)
        if cnt != N_SEED - 2:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — I3: idempotent "
                  f"re-delete must not consume fresh survivors; count expected "
                  f"{N_SEED - 2}, got {cnt}: {str(craw)[:300]}")
            return
        print(f"I3: 200 again, count still == {cnt} == {N_SEED - 2} (idempotent)")

        # ---- I4: mixed [999 non-existent, 3 existing] -> 200, count 3 ----
        s4, _, raw4 = delete_points(coll, [999, 3])
        print(f"\nI4 delete mixed ids [999(non-existent), 3(existing)] -> status={s4}")
        print(f"raw: {raw4[:400]}")
        if s4 == -1:
            transport_dead("I4")
            return
        if 500 <= s4 <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — I4: mixed-list delete returned {s4}: {raw4[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — I4 5xx and healthz down")
            return
        if not (200 <= s4 <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — I4: mixed-list "
                  f"delete rejected with {s4} (a non-existent id inside a valid "
                  f"list must not fail the request): {raw4[:300]}")
            return
        cnt, cs, craw = exact_count(coll)
        if cnt != N_SEED - 3:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — I4: count "
                  f"expected {N_SEED - 3} (only id 3 consumable), got {cnt}: {str(craw)[:300]}")
            return
        print(f"I4: 200, count == {cnt} == {N_SEED - 3}")

        # ---- cross-face close-out: scroll must return exactly {4,5,6} ----
        s5, b5, raw5 = safe_request("POST", f"/collections/{coll}/points/scroll",
                                    json={"limit": 20, "with_payload": False,
                                          "with_vector": False}, timeout=60)
        print(f"\ncross-face scroll (no filter) -> status={s5}")
        print(f"raw: {raw5[:400]}")
        if s5 == -1:
            transport_dead("cross-face scroll")
            return
        if 500 <= s5 <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — scroll cross-face returned {s5}: {raw5[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — scroll 5xx and healthz down")
            return
        if not (200 <= s5 <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — scroll cross-face rejected with {s5}: {raw5[:300]}")
            return
        result5 = b5.get("result") if isinstance(b5, dict) else None
        pts5 = result5.get("points") if isinstance(result5, dict) else None
        if not isinstance(pts5, list):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — scroll "
                  f"result.points not an array (response_shape result.points): {raw5[:300]}")
            return
        got_ids = {p.get("id") for p in pts5 if isinstance(p, dict)}
        if got_ids != set(SURVIVORS_AFTER_I4):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — cross-face "
                  f"disagreement: count face says {N_SEED - 3} but scroll face "
                  f"returns ids {sorted(got_ids)} (expected exactly {SURVIVORS_AFTER_I4}): {raw5[:300]}")
            return
        print(f"cross-face: scroll id set == {sorted(got_ids)} (count/scroll faces agree)")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
