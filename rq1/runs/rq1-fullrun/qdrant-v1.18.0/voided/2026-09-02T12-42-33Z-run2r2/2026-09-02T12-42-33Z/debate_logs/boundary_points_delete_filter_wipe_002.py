#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_delete_filter_wipe_002
# strategy: strategy1 boundary-value attack (filter-form delete promise:
#           match-scoped removal + match-all wipe, arithmetic-derived
#           survivor counts and cross-face id-set equality)
# endpoint: points+delete
# constraint_ids: qdrant_state_points_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/delete-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — "filter-based delete removes
#            every matching point (all points when the filter is empty/matches
#            everything)" is trusted at its two degenerate match-all forms)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary x qdrant_state_points_delete_001 — the filter leg
  "filter-based delete removes every matching point (all points when the
  filter is empty/matches everything)" is exercised at three faces, every
  survivor count derived arithmetically from the seed set (R33 lesson:
  count/delete expectations arithmetic-derived with id-collision analysis —
  fresh uuid-tagged collection, prefix-unique ids, no pre-existing collision):
    W1 seed ids 1..6 city=berlin + ids 7..10 city=paris (10 total);
       delete filter must[city=berlin] -> 200, count 10-6=4, scroll face
       must return EXACTLY the 4 paris ids {7,8,9,10}
    W2 delete filter {} (empty filter = matches everything per the
       constraint's own wording) -> 200, count 0, scroll face empty
    W3 re-seed ids 21..25 city=oslo (5 total); delete filter {"must": []}
       (empty clause list = zero conditions = second match-all form) -> 200,
       count 0, scroll face empty; divergent disposition vs W2 (G9:
       inconsistent disposition of same-shape selector forms) is reported
  Persistence judged via count+scroll cross-face (R34 lesson).
  [chunk_points+delete coverage: strategy1 filter-wipe faces x
  qdrant_state_points_delete_001 (this script; idempotence faces in
  boundary_points_delete_idempotent_001, 404 leg in
  boundary_points_delete_404_003, invalid-filter 400 leg in
  boundary_points_delete_invalid_filter_004, selector-boundary faces in
  boundary_points_delete_selector_005, cross-face invisibility in
  boundary_points_delete_invisibility_006)]
Oracle: W1 -> 200 with count face == 4 AND scroll id set == exactly
  {7,8,9,10} (any berlin survivor or paris casualty = Type4_StateLogicViolation;
  4xx on the valid filter delete = Type1_IllegalSuccess); W2/W3 -> 200 with
  count == 0 AND scroll result.points == [] (survivor = Type4); W3 4xx while
  W2 succeeded = Type1 + G9 inconsistent disposition of the two match-all
  forms; 5xx with /healthz alive = Type3_RuntimeFailure; transport failure ->
  /healthz liveness re-check then SCRIPT_ERROR
  (constraint qdrant_state_points_delete_001).
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
BERLIN_N = 6
PARIS_N = 4
N_SEED = BERLIN_N + PARIS_N  # 10
V = [0.1, 0.2, 0.3, 0.4]
PARIS_IDS = list(range(BERLIN_N + 1, N_SEED + 1))  # 7..10
OSLO_IDS = [21, 22, 23, 24, 25]


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


def exact_count(coll):
    """Exact count via the points+count face (result.count integer per shape)."""
    s, body, raw = safe_request("POST", f"/collections/{coll}/points/count",
                                json={"exact": True}, timeout=60)
    if s == -1 or not (200 <= s <= 299):
        return None, s, raw
    result = body.get("result") if isinstance(body, dict) else None
    got = result.get("count") if isinstance(result, dict) else None
    return got, s, raw


def scroll_ids(coll, filt=None):
    """Scroll face id set (result.points[].id per response_shape)."""
    body = {"limit": 50, "with_payload": False, "with_vector": False}
    if filt is not None:
        body["filter"] = filt
    s, b, raw = safe_request("POST", f"/collections/{coll}/points/scroll",
                             json=body, timeout=60)
    if s == -1 or not (200 <= s <= 299):
        return None, s, raw
    result = b.get("result") if isinstance(b, dict) else None
    pts = result.get("points") if isinstance(result, dict) else None
    if not isinstance(pts, list):
        return None, s, raw
    return {p.get("id") for p in pts if isinstance(p, dict)}, s, raw


def delete_filter(coll, filt):
    """Filter-selector delete on the points+delete face, wait=true (query param)."""
    return safe_request("POST", f"/collections/{coll}/points/delete",
                        json={"filter": filt}, timeout=60, params={"wait": "true"})


def judge_delete_status(label, status, raw, match_all_baseline_ok):
    """Common status adjudication for a valid filter delete. None=ok, else exits."""
    if status == -1:
        return transport_dead(label)
    if 500 <= status <= 599:
        alive, _, _ = healthz_alive()
        if alive:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {label}: valid "
                  f"filter delete returned {status}: {raw[:300]}")
        else:
            print("VERDICT: SCRIPT_ERROR — {l} 5xx and healthz down".format(l=label))
        return True
    if not (200 <= status <= 299):
        # 4xx on a filter delete that the constraint explicitly allows
        if match_all_baseline_ok:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: filter "
                  f"delete rejected with {status}; constraint promises delete by "
                  f"filter is allowed and match-all wipes all (G9: the equivalent "
                  f"match-all form on this collection succeeded): {raw[:300]}")
        else:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: valid "
                  f"filter delete rejected with {status} (promise: HTTP 200): {raw[:300]}")
        return True
    return False


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpd2w" + tag

    # Arrange: own collection + seed set (R34 arithmetic discipline)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
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
        cnt, cs, craw = exact_count(coll)
        if cnt != N_SEED:
            print(f"seed count = {cnt} (status={cs}), expected {N_SEED}: {str(craw)[:200]}")
            print("VERDICT: SCRIPT_ERROR — setup baseline mismatch")
            return
        print(f"seed baseline: exact count == {N_SEED} ({BERLIN_N} berlin + {PARIS_N} paris)")

        # ---- W1: match-scoped filter delete (city=berlin) ----
        s1, _, raw1 = delete_filter(coll, {"must": [match_cond("city", "berlin")]})
        print(f"\nW1 delete filter must[city=berlin] -> status={s1}")
        print(f"raw: {raw1[:400]}")
        if judge_delete_status("W1", s1, raw1, match_all_baseline_ok=False):
            return
        cnt, cs, craw = exact_count(coll)
        if cnt != PARIS_N:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — W1: count "
                  f"expected {PARIS_N} ({N_SEED} - {BERLIN_N} berlin deleted), got "
                  f"{cnt}: {str(craw)[:300]}")
            return
        ids, ss, sraw = scroll_ids(coll)
        if ids is None:
            print(f"W1 scroll cross-face failed status={ss}: {str(sraw)[:300]}")
            print("VERDICT: SCRIPT_ERROR — read-face failure, no defect conclusion")
            return
        if ids != set(PARIS_IDS):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — W1: count "
                  f"face says {PARIS_N} but scroll face returns {sorted(ids)} "
                  f"(expected exactly {PARIS_IDS}) — leaked berlin survivor or "
                  f"paris casualty: {str(sraw)[:300]}")
            return
        print(f"W1: 200, count == {cnt} == {PARIS_N}, scroll id set == {PARIS_IDS} (cross-face agree)")

        # ---- W2: match-all empty filter {} (whole-collection wipe) ----
        s2, _, raw2 = delete_filter(coll, {})
        print(f"\nW2 delete filter {{}} (empty = matches everything) -> status={s2}")
        print(f"raw: {raw2[:400]}")
        if judge_delete_status("W2", s2, raw2, match_all_baseline_ok=False):
            return
        cnt, cs, craw = exact_count(coll)
        if cnt != 0:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — W2: empty "
                  f"filter matches everything; expected 0 survivors, got {cnt}: {str(craw)[:300]}")
            return
        ids, ss, sraw = scroll_ids(coll)
        if ids is None:
            print(f"W2 scroll cross-face failed status={ss}: {str(sraw)[:300]}")
            print("VERDICT: SCRIPT_ERROR — read-face failure, no defect conclusion")
            return
        if ids != set():
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — W2: scroll "
                  f"face still returns ids {sorted(ids)} after match-all wipe: {str(sraw)[:300]}")
            return
        print("W2: 200, count == 0, scroll empty — match-all wipe complete")

        # ---- W3: second match-all form {"must": []} on a fresh re-seed ----
        points3 = [{"id": i, "vector": V, "payload": {"city": "oslo"}} for i in OSLO_IDS]
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": points3}, params={"wait": "true"}, timeout=120)
        if s not in (200, 201):
            print(f"W3 re-seed upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return
        cnt, cs, craw = exact_count(coll)
        if cnt != len(OSLO_IDS):
            print(f"W3 re-seed count = {cnt} (status={cs}), expected {len(OSLO_IDS)}: {str(craw)[:200]}")
            print("VERDICT: SCRIPT_ERROR — setup baseline mismatch")
            return
        s3, _, raw3 = delete_filter(coll, {"must": []})
        print(f"\nW3 delete filter {{\"must\": []}} (empty clause list = zero conditions) -> status={s3}")
        print(f"raw: {raw3[:400]}")
        if judge_delete_status("W3", s3, raw3, match_all_baseline_ok=True):
            return
        cnt, cs, craw = exact_count(coll)
        if cnt != 0:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — W3: empty "
                  f"clause list carries zero conditions (matches everything); "
                  f"expected 0 survivors, got {cnt}: {str(craw)[:300]}")
            return
        ids, ss, sraw = scroll_ids(coll)
        if ids is None:
            print(f"W3 scroll cross-face failed status={ss}: {str(sraw)[:300]}")
            print("VERDICT: SCRIPT_ERROR — read-face failure, no defect conclusion")
            return
        if ids != set():
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — W3: scroll "
                  f"face still returns ids {sorted(ids)} after match-all wipe: {str(sraw)[:300]}")
            return
        print("W3: 200, count == 0, scroll empty — second match-all form agrees with W2 (G9 consistent)")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
