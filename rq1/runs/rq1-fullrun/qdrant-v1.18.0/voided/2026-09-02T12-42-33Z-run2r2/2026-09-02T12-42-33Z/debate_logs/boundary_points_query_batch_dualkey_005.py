#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_query_batch_dualkey_005
# strategy: strategy2 dual-key enum attack — R33 proven defect family
#           (serde untagged dual-key elements silently discard the second
#           key, REST-only, points+batch) re-applied to the query oneOf
#           enum inside a batch entry: two variant keys present
#           simultaneously in entry.query
# endpoint: points+query+batch
# constraint_ids: qdrant_behavioral_points_query_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/batch-query
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — the contract types query
#            as oneOf nearest/recommend/discover/context/order_by/fusion/
#            sample/...; an entry whose query object carries TWO variant
#            keys at once violates oneOf — silent acceptance with one key
#            discarded is the R33 key-discard family on a new wrapper)
# exploration_target: novel_candidate
# shape_id: dual_key_enum_discard
# shape_type: type_confusion
# generalized_from: R33 points+batch dual-key key-discard (proven family)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: R33-family dual-key enum x
  qdrant_behavioral_points_query_batch_001 — the per-entry query field is a
  oneOf enum (contract parameter note: "oneOf nearest/recommend/discover/
  context/order_by/fusion/sample/neartext/nearimage"). Dual-key faces, each
  as a single-entry batch with DISJOINT deterministic fingerprints (seeded
  red ids 1-3 on axis-1, blue ids 4-9 on axis-2, rank=i):
    D1 query={"nearest": blue-vec, "order_by": rank asc} limit 3
       fp_order_by  = ids exactly [1,2,3] (rank ascending)
       fp_nearest   = ids subset of {4..9} (blue directions)
       oneOf violated -> strict expectation 422; a 200 whose ids match
       EXACTLY ONE fingerprint proves the other variant key was silently
       discarded (which key "won" is recorded).
    D2 query={"order_by": rank asc, "sample": "random"} limit 3
       secondary face: sample=random yields arbitrary ids; a 200 with ids
       exactly [1,2,3] proves sample was discarded in favor of order_by
       (random coincidence chance noted, 1/C(9,3) ~ 0.8%).
  [chunk_points+query+batch coverage: strategy1 positive order/count core x
  behavioral_points_query_batch_001 (positive_001); assertion 404 leg x
  behavioral_points_query_batch_001 (404_002); strategy2 searches wrapper
  type x behavioral_points_query_batch_001 (searches_type_003); strategy2
  entry presence matrix x behavioral_points_query_batch_001 (presence_004);
  R33-family dual-key enum discard x behavioral_points_query_batch_001
  (this script); strategy1 per-entry limit x behavioral_points_query_batch_001
  + range_points_query_001 min-1 ground (limit_006); strategy1 per-entry
  offset x behavioral_points_query_batch_001 + range_points_query_001 min-0
  ground (offset_007); mixed-variant universal-queries promise x
  behavioral_points_query_batch_001 (mixed_008); strategy6 batch-size
  resource x behavioral_points_query_batch_001 (resource_009); strategy7
  malformed stream x behavioral_points_query_batch_001 (malformed_010)]
Oracle: D1/D2 -> 400/422 (oneOf: two variant keys present simultaneously
  must not validate; strict rejection is the clean disposition); 200 with
  ids matching exactly ONE variant fingerprint = Type1_IllegalSuccess
  candidate — the second key silently discarded, executed query differs
  from a strict reading of the request (R33 proven family; recorded with
  the winning key for judge adjudication); 200 with ids matching NEITHER
  fingerprint = Type4_StateLogicViolation; 5xx with /healthz alive =
  Type3_RuntimeFailure; transport failure -> /healthz liveness re-check
  then SCRIPT_ERROR (constraint qdrant_behavioral_points_query_batch_001).
Constraint: qdrant_behavioral_points_query_batch_001 (bare id) — "executes
  multiple queries in one call; returns 200 with a list of per-query results;
  404 for a missing collection" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+query+batch    -> POST /collections/{collection_name}/points/query/batch
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
RED_IDS = set(range(1, RED_N + 1))
BLUE_IDS = set(range(RED_N + 1, N_SEED + 1))
BLUE_VEC = [0.0, 1.0, 0.0, 0.0]
ORDER_BY_ASC = {"key": "rank", "direction": "asc"}
FP_ORDER_BY = [1, 2, 3]  # rank == id, ascending -> exactly these ids


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


def batch_ids(body):
    """ids list of result[0] for a single-entry batch; None on any mismatch."""
    if not isinstance(body, dict):
        return None
    res = body.get("result")
    if not isinstance(res, list) or len(res) != 1:
        return None
    elem = res[0]
    if not isinstance(elem, dict) or not isinstance(elem.get("points"), list):
        return None
    out = []
    for p in elem["points"]:
        if not isinstance(p, dict) or "id" not in p:
            return None
        out.append(p.get("id"))
    return out


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpqb5" + tag

    ok, raw = setup(coll)
    if not ok:
        print(f"setup failed: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        # --- D1: nearest + order_by (disjoint deterministic fingerprints) ---
        d1 = {"query": {"nearest": list(BLUE_VEC),
                        "order_by": dict(ORDER_BY_ASC)}, "limit": 3}
        s, body, raw = safe_request(
            "POST", f"/collections/{coll}/points/query/batch",
            json={"searches": [d1]}, timeout=60)
        print(f"D1 nearest+order_by dual-key -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            alive, hs, hraw = healthz_alive()
            print(f"transport failure on D1 (healthz status={hs}: {hraw})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — D1: "
                      f"returned {s}: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — D1 5xx and healthz down")
            return
        if s in (400, 422):
            print("D1 clean rejection: oneOf enforced (both keys honored)")
        elif 200 <= s <= 299:
            got = batch_ids(body)
            if got is None:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                      f"D1: 200 but result not one element carrying a points "
                      f"array: {raw[:300]}")
                return
            gset = set(got)
            match_ob = (got == FP_ORDER_BY)
            match_near = bool(gset) and gset <= BLUE_IDS
            if match_ob and not match_near:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — D1: "
                      f"dual-key query ACCEPTED with 200; ids {got} match the "
                      f"order_by fingerprint exactly, so the simultaneous "
                      f"\"nearest\" key was silently DISCARDED (R33 "
                      f"key-discard family, query oneOf wrapper; winning key: "
                      f"order_by): {raw[:200]}")
                return
            if match_near and not match_ob:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — D1: "
                      f"dual-key query ACCEPTED with 200; ids {got} match the "
                      f"nearest fingerprint, so the simultaneous \"order_by\" "
                      f"key was silently DISCARDED (R33 key-discard family, "
                      f"query oneOf wrapper; winning key: nearest): "
                      f"{raw[:200]}")
                return
            if not match_ob and not match_near:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                      f"D1: 200 but ids {got} match NEITHER variant "
                      f"fingerprint (order_by=={FP_ORDER_BY}, nearest subset "
                      f"of blue): {raw[:300]}")
                return
            # both match is impossible (fingerprints disjoint)
        else:
            print(f"NOTE (judge): D1 returned {s}; recorded for the judge")

        # --- D2: order_by + sample (secondary face) ---
        d2 = {"query": {"order_by": dict(ORDER_BY_ASC), "sample": "random"},
              "limit": 3}
        s2, body2, raw2 = safe_request(
            "POST", f"/collections/{coll}/points/query/batch",
            json={"searches": [d2]}, timeout=60)
        print(f"\nD2 order_by+sample dual-key -> status={s2}")
        print(f"raw: {raw2[:400]}")
        if s2 == -1:
            alive, hs, hraw = healthz_alive()
            print(f"transport failure on D2 (healthz status={hs}: {hraw})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if 500 <= s2 <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — D2: "
                      f"returned {s2}: {raw2[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — D2 5xx and healthz down")
            return
        if s2 in (400, 422):
            print("D2 clean rejection: oneOf enforced (both keys honored)")
        elif 200 <= s2 <= 299:
            got2 = batch_ids(body2)
            if got2 is None:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                      f"D2: 200 but result not one element carrying a points "
                      f"array: {raw2[:300]}")
                return
            if got2 == FP_ORDER_BY:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — D2: "
                      f"dual-key query ACCEPTED with 200; ids {got2} match "
                      f"the order_by fingerprint, so the simultaneous "
                      f"\"sample\" key was silently DISCARDED (R33 "
                      f"key-discard family; ~0.8% random-coincidence chance "
                      f"noted): {raw2[:200]}")
                return
            print(f"D2 judge-call: 200 with ids {got2} (sample disposition "
                  f"or mixed semantics); recorded for the judge")
        else:
            print(f"NOTE (judge): D2 returned {s2}; recorded for the judge")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
