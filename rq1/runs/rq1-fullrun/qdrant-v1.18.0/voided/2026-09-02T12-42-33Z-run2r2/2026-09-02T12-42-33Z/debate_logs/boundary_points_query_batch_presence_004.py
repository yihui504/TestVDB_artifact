#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_query_batch_presence_004
# strategy: strategy2 presence/optionality matrix on the per-entry fields —
#           the QueryRequest embedded in each searches[] element re-tests the
#           documented optionality semantics on the batch face (G9 parity
#           with the single face, measured live in the same run)
# endpoint: points+query+batch
# constraint_ids: qdrant_behavioral_points_query_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/batch-query
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust / presence optimism — the
#            per-entry dispatcher could accept an entry with NO basis at all
#            ({} — falls back to id-order browse per the single-face
#            documented behavior) or silently drop unknown entry keys,
#            degrading a mistyped query to an id-order browse with 200)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 entry presence matrix x
  qdrant_behavioral_points_query_batch_001, each face sent as a SINGLE-entry
  batch (attribution stays clean) on a seeded 9-point collection:
    E1 empty entry {}            — query absent, no prefetch: the single face
       documents "points ordered by their ids" (contract parameter note +
       sibling assertion qdrant_behavioral_points_query_004); the batch face
       must uphold the same semantics (G9). A live single-face call with the
       same entry body is the measured baseline.
    E2 filter-only entry         — no query; filtered points in id order.
    E3 query-only entry          — nearest, no filter: valid positive face.
    E4 unknown entry key         — {"bogus_query": {...}}: judge-call face;
       a 200 that silently degrades to the id-order browse (unknown key
       dropped) is the R33-family silent-drop shape on a new wrapper;
       a 4xx is equally defensible. Recorded for the judge.
  [chunk_points+query+batch coverage: strategy1 positive order/count core x
  behavioral_points_query_batch_001 (positive_001); assertion 404 leg x
  behavioral_points_query_batch_001 (404_002); strategy2 searches wrapper
  type x behavioral_points_query_batch_001 (searches_type_003); strategy2
  entry presence matrix x behavioral_points_query_batch_001 (this script);
  R33-family dual-key enum discard x behavioral_points_query_batch_001
  (dualkey_005); strategy1 per-entry limit x behavioral_points_query_batch_001
  + range_points_query_001 min-1 ground (limit_006); strategy1 per-entry
  offset x behavioral_points_query_batch_001 + range_points_query_001 min-0
  ground (offset_007); mixed-variant universal-queries promise x
  behavioral_points_query_batch_001 (mixed_008); strategy6 batch-size
  resource x behavioral_points_query_batch_001 (resource_009); strategy7
  malformed stream x behavioral_points_query_batch_001 (malformed_010)]
Oracle: E1 -> 200, result[0].points ids ascending == [1..9] (default limit
  10 >= 9) AND identical id list to the live-measured single-face baseline
  (batch rejects E1 while the single face accepts = G9 asymmetry defect
  signal; wrong order/count = Type4); E2 -> 200, ids ascending == [4..9];
  E3 -> 200, <=3 points (rejection of the documented-legal query-only entry
  = Type1_IllegalSuccess convention); E4 -> 4xx or 200-with-id-order-browse
  (both recorded for the judge; 200 with a NON-id-order result = Type4);
  5xx with /healthz alive = Type3_RuntimeFailure; transport failure ->
  /healthz liveness re-check then SCRIPT_ERROR (constraint
  qdrant_behavioral_points_query_batch_001).
Constraint: qdrant_behavioral_points_query_batch_001 (bare id) — "executes
  multiple queries in one call; returns 200 with a list of per-query results;
  404 for a missing collection" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+query+batch    -> POST /collections/{collection_name}/points/query/batch
  points+query          -> POST /collections/{collection_name}/points/query
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
ALL_IDS_ASC = list(range(1, N_SEED + 1))
BLUE_IDS_ASC = list(range(RED_N + 1, N_SEED + 1))


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
    """Inline liveness probe on the lightweight healthz face."""
    hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
    return hs == 200, hs, str(hraw)[:200]


def point_vec(i):
    if i <= RED_N:
        return [1.0, round(0.001 * i, 4), 0.0, 0.0]
    return [round(0.001 * i, 4), 1.0, 0.0, 0.0]


def setup(coll):
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Cosine"}},
                             timeout=60)
    if s not in (200, 201):
        return False, raw
    pts = [{"id": i, "vector": point_vec(i),
            "payload": {"grp": "red" if i <= RED_N else "blue", "rank": i}}
           for i in range(1, N_SEED + 1)]
    s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                             json={"points": pts}, params={"wait": "true"},
                             timeout=120)
    if s not in (200, 201):
        return False, raw
    return True, ""


def query_batch(coll, entry):
    return safe_request("POST", f"/collections/{coll}/points/query/batch",
                        json={"searches": [entry]}, timeout=60)


def query_single(coll, entry):
    return safe_request("POST", f"/collections/{coll}/points/query",
                        json=entry, timeout=60)


def ids_of_entry(res_elem):
    """ids of one per-query result element; None on shape violation
    (response_shape: result[].points)."""
    if not isinstance(res_elem, dict) or not isinstance(res_elem.get("points"), list):
        return None
    out = []
    for p in res_elem["points"]:
        if not isinstance(p, dict) or "id" not in p:
            return None
        out.append(p.get("id"))
    return out


def batch_ids(body):
    """ids list of result[0] for a single-entry batch; None on any mismatch."""
    if not isinstance(body, dict):
        return None
    res = body.get("result")
    if not isinstance(res, list) or len(res) != 1:
        return None
    return ids_of_entry(res[0])


def single_ids(body):
    """ids list for the single-face result object (result.points)."""
    if not isinstance(body, dict):
        return None
    res = body.get("result")
    if not isinstance(res, dict) or not isinstance(res.get("points"), list):
        return None
    out = []
    for p in res["points"]:
        if not isinstance(p, dict) or "id" not in p:
            return None
        out.append(p.get("id"))
    return out


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpqb4" + tag

    ok, raw = setup(coll)
    if not ok:
        print(f"setup failed: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        # --- E1: empty entry {} — id-order browse, batch vs single parity ---
        e1 = {}
        s1, b1, r1 = query_batch(coll, e1)
        sg, bg, rg = query_single(coll, dict(e1))
        print(f"E1 empty entry {{}} -> batch status={s1}, single status={sg}")
        print(f"batch raw: {r1[:300]}")
        print(f"single raw: {rg[:300]}")
        if s1 == -1 or sg == -1:
            alive, hs, hraw = healthz_alive()
            print(f"transport failure on E1 (healthz status={hs}: {hraw})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if 500 <= s1 <= 599 or 500 <= sg <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — E1: "
                      f"5xx (batch={s1}, single={sg})")
            else:
                print("VERDICT: SCRIPT_ERROR — E1 5xx and healthz down")
            return
        base_ids = single_ids(bg) if 200 <= sg <= 299 else None
        if base_ids is not None:
            print(f"E1 single-face baseline ids (live-measured): {base_ids}")
        if not (200 <= s1 <= 299):
            if 200 <= sg <= 299:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — E1: "
                      f"batch face rejects the documented query-absent entry "
                      f"with {s1} while the single face accepts it with {sg} "
                      f"(G9 asymmetry on the same documented semantics)")
            else:
                print(f"NOTE (judge): E1 rejected on both faces (batch={s1}, "
                      f"single={sg}); recorded for the judge")
            return
        got = batch_ids(b1)
        if got is None:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — E1: "
                  f"200 but result not one element carrying a points array: "
                  f"{r1[:300]}")
            return
        if got != ALL_IDS_ASC:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — E1: "
                  f"query-absent entry must return points ordered by id "
                  f"(expected {ALL_IDS_ASC}, got {got}): {r1[:300]}")
            return
        if base_ids is not None and got != base_ids:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — E1: "
                  f"batch id-order {got} differs from live single-face "
                  f"baseline {base_ids} for the identical entry body (G9)")
            return
        print(f"E1 upheld: batch id-order browse == {got}, matches single face")

        # --- E2: filter-only entry (no query) — filtered id order ---
        e2 = {"filter": {"must": [{"key": "grp",
                                   "match": {"value": "blue"}}]}, "limit": 20}
        s2, b2, r2 = query_batch(coll, e2)
        print(f"\nE2 filter-only entry -> status={s2}")
        print(f"raw: {r2[:300]}")
        if s2 == -1:
            alive, hs, hraw = healthz_alive()
            print(f"transport failure on E2 (healthz status={hs}: {hraw})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if 500 <= s2 <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — E2: "
                      f"returned {s2}: {r2[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — E2 5xx and healthz down")
            return
        if not (200 <= s2 <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — E2: valid "
                  f"filter-only entry rejected with {s2} (query is optional "
                  f"per contract): {r2[:300]}")
            return
        got2 = batch_ids(b2)
        if got2 != BLUE_IDS_ASC:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — E2: "
                  f"filter-only entry must return filtered points in id "
                  f"order (expected {BLUE_IDS_ASC}, got {got2}): {r2[:300]}")
            return
        print(f"E2 upheld: filtered id-order == {got2}")

        # --- E3: query-only entry (no filter) — valid positive face ---
        e3 = {"query": {"nearest": [0.0, 1.0, 0.0, 0.0]}, "limit": 3}
        s3, b3, r3 = query_batch(coll, e3)
        print(f"\nE3 query-only entry -> status={s3}")
        print(f"raw: {r3[:300]}")
        if s3 == -1:
            alive, hs, hraw = healthz_alive()
            print(f"transport failure on E3 (healthz status={hs}: {hraw})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if 500 <= s3 <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — E3: "
                      f"returned {s3}: {r3[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — E3 5xx and healthz down")
            return
        if not (200 <= s3 <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — E3: valid "
                  f"query-only entry rejected with {s3} (promise: HTTP 200): "
                  f"{r3[:300]}")
            return
        got3 = batch_ids(b3)
        if got3 is None or not (len(got3) <= 3):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — E3: "
                  f"result shape/count broken (limit 3), got {got3}: "
                  f"{r3[:300]}")
            return
        print(f"E3 upheld: query-only entry, {len(got3)} points")

        # --- E4: unknown entry key (judge-call face) ---
        e4 = {"bogus_query": {"nearest": [0.0, 1.0, 0.0, 0.0]}, "limit": 3}
        s4, b4, r4 = query_batch(coll, e4)
        print(f"\nE4 unknown entry key -> status={s4}")
        print(f"raw: {r4[:300]}")
        if s4 == -1:
            alive, hs, hraw = healthz_alive()
            print(f"transport failure on E4 (healthz status={hs}: {hraw})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if 500 <= s4 <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — E4: "
                      f"returned {s4}: {r4[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — E4 5xx and healthz down")
            return
        if 200 <= s4 <= 299:
            got4 = batch_ids(b4)
            if got4 == ALL_IDS_ASC[:3]:
                print(f"E4 judge-call face: 200 with ids {got4} == id-order "
                      f"browse first 3 — unknown key silently DROPPED, entry "
                      f"degraded to query-absent browse (R33-family "
                      f"silent-drop shape); recorded for the judge")
            elif got4 is None:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                      f"E4: 200 but result not one element carrying a points "
                      f"array: {r4[:300]}")
                return
            else:
                print(f"E4 judge-call face: 200 with ids {got4} (neither a "
                      f"clean reject nor the id-order browse); recorded for "
                      f"the judge")
        elif s4 in (400, 422):
            print(f"E4 judge-call face: {s4} clean rejection; recorded for "
                  f"the judge")
        else:
            print(f"NOTE (judge): E4 returned {s4}; recorded for the judge")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
