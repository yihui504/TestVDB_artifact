#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_query_batch_mixed_008
# strategy: strategy1/semantic hybrid on the batch mixing promise — the
#           endpoint description is "Execute multiple universal queries in
#           one call": heterogeneous variant entries in ONE batch are the
#           documented use case (contrast: R37 found discover+batch mixed
#           batches whole-rejected — this face's promise is broader, so
#           whole-rejection here would violate the promise, not mirror it)
# endpoint: points+query+batch
# constraint_ids: qdrant_behavioral_points_query_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/batch-query
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — clients batch heterogeneous
#            query variants trusting the "universal queries" wording; a
#            whole-batch rejection or per-entry limit bleed breaks the
#            one-result-per-search promise silently)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: mixed-variant universal-queries promise x
  qdrant_behavioral_points_query_batch_001 on a seeded 9-point collection
  (red ids 1-3 axis-1, blue ids 4-9 axis-2, rank=i):
    M1 heterogeneous batch [nearest(blue), order_by(rank asc), filter-only
       (grp=red)] -> 200, outer len EXACTLY 3, per-entry attribution:
       result[0] subset blue, result[1] == [1,2,3], result[2] == [1,2,3]
       ascending (red filter in id order).
    M2 duplicate identical entries (nearest blue, exact=true, limit 3) x2
       -> outer len 2, both results IDENTICAL id lists (determinism device
       only — exact=true is documented stable ordering, no invented score
       oracle).
    M3 per-entry limit independence [limit=1, limit=3, limit=5] on nearest
       blue entries -> len(result[i].points) EXACTLY limit_i (a limit bleed
       across entries breaks per-entry pagination arithmetic).
  [chunk_points+query+batch coverage: strategy1 positive order/count core x
  behavioral_points_query_batch_001 (positive_001); assertion 404 leg x
  behavioral_points_query_batch_001 (404_002); strategy2 searches wrapper
  type x behavioral_points_query_batch_001 (searches_type_003); strategy2
  entry presence matrix x behavioral_points_query_batch_001 (presence_004);
  R33-family dual-key enum discard x behavioral_points_query_batch_001
  (dualkey_005); strategy1 per-entry limit x behavioral_points_query_batch_001
  + range_points_query_001 min-1 ground (limit_006); strategy1 per-entry
  offset x behavioral_points_query_batch_001 + range_points_query_001 min-0
  ground (offset_007); mixed-variant universal-queries promise x
  behavioral_points_query_batch_001 (this script); strategy6 batch-size
  resource x behavioral_points_query_batch_001 (resource_009); strategy7
  malformed stream x behavioral_points_query_batch_001 (malformed_010)]
Oracle: M1 -> 200 outer len EXACTLY 3 with the per-entry fingerprints above
  (whole-batch 4xx = Type1_IllegalSuccess convention: heterogeneous
  "universal queries" batch is the documented use; wrong attribution/shape =
  Type4); M2 -> 200 outer len 2 with identical id lists (differing lists
  under exact=true = Type4 nondeterminism); M3 -> 200 with
  len(result[i].points) == 1/3/5 exactly (limit bleed = Type4); 5xx with
  /healthz alive = Type3_RuntimeFailure; transport failure -> /healthz
  liveness re-check then SCRIPT_ERROR (constraint
  qdrant_behavioral_points_query_batch_001).
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
RED_ASC = list(range(1, RED_N + 1))
BLUE_VEC = [0.0, 1.0, 0.0, 0.0]


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


def query_batch(coll, body, timeout=60):
    return safe_request("POST", f"/collections/{coll}/points/query/batch",
                        json=body, timeout=timeout)


def entry_ids(res_elem):
    if not isinstance(res_elem, dict) or not isinstance(res_elem.get("points"), list):
        return None
    out = []
    for p in res_elem["points"]:
        if not isinstance(p, dict) or "id" not in p:
            return None
        out.append(p.get("id"))
    return out


def guard(label, s, raw):
    """Transport/5xx guard; returns 'stop' after printing, else None."""
    if s == -1:
        alive, hs, hraw = healthz_alive()
        print(f"transport failure on {label} (healthz status={hs}: {hraw})")
        print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
        return "stop"
    if 500 <= s <= 599:
        alive, _, _ = healthz_alive()
        if alive:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {label}: "
                  f"returned {s}: {raw[:300]}")
        else:
            print(f"VERDICT: SCRIPT_ERROR — {label} 5xx and healthz down")
        return "stop"
    return None


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpqb8" + tag

    ok, raw = setup(coll)
    if not ok:
        print(f"setup failed: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        # --- M1: heterogeneous batch (the documented "universal queries" use) ---
        m1 = {"searches": [
            {"query": {"nearest": list(BLUE_VEC)}, "limit": 3},
            {"query": {"order_by": {"key": "rank", "direction": "asc"}},
             "limit": 3},
            {"filter": {"must": [{"key": "grp",
                                  "match": {"value": "red"}}]}, "limit": 20},
        ]}
        s, body, raw = query_batch(coll, m1)
        print(f"M1 heterogeneous batch -> status={s}")
        print(f"raw: {raw[:500]}")
        if guard("M1", s, raw) == "stop":
            return
        if not (200 <= s <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — M1: "
                  f"heterogeneous universal-queries batch REJECTED with {s} "
                  f"(endpoint promise: execute multiple universal queries in "
                  f"one call): {raw[:300]}")
            return
        res = body.get("result") if isinstance(body, dict) else None
        if not isinstance(res, list) or len(res) != 3:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — M1: "
                  f"outer result len={len(res) if isinstance(res, list) else 'non-list'} "
                  f"(expected 3, N-in/N-out): {raw[:300]}")
            return
        i0, i1, i2 = entry_ids(res[0]), entry_ids(res[1]), entry_ids(res[2])
        if i0 is None or i1 is None or i2 is None:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — M1: "
                  f"a result element is not an object carrying a points "
                  f"array: {raw[:300]}")
            return
        if not (set(i0) <= BLUE_IDS and len(i0) <= 3):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — M1 "
                  f"result[0]: nearest(blue) attribution broken, got "
                  f"{i0}: {raw[:300]}")
            return
        if i1 != [1, 2, 3]:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — M1 "
                  f"result[1]: order_by rank asc attribution broken, "
                  f"expected [1, 2, 3], got {i1}: {raw[:300]}")
            return
        if i2 != RED_ASC:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — M1 "
                  f"result[2]: filter-only red entry must return red ids "
                  f"ascending, expected {RED_ASC}, got {i2}: {raw[:300]}")
            return
        print(f"M1 upheld: {i0} / {i1} / {i2}")

        # --- M2: duplicate identical entries, exact=true determinism ---
        dup = {"query": {"nearest": list(BLUE_VEC)}, "limit": 3,
               "params": {"exact": True}}
        m2 = {"searches": [dict(dup), dict(dup)]}
        s2, body2, raw2 = query_batch(coll, m2)
        print(f"\nM2 duplicate entries -> status={s2}")
        print(f"raw: {raw2[:400]}")
        if guard("M2", s2, raw2) == "stop":
            return
        if not (200 <= s2 <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — M2: valid "
                  f"duplicate-entry batch rejected with {s2}: {raw2[:300]}")
            return
        res2 = body2.get("result") if isinstance(body2, dict) else None
        if not isinstance(res2, list) or len(res2) != 2:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — M2: "
                  f"outer result len={len(res2) if isinstance(res2, list) else 'non-list'} "
                  f"(expected 2): {raw2[:300]}")
            return
        d0, d1 = entry_ids(res2[0]), entry_ids(res2[1])
        if d0 is None or d1 is None:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — M2: "
                  f"result element shape broken: {raw2[:300]}")
            return
        if d0 != d1:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — M2: "
                  f"identical entries (exact=true) returned DIFFERENT "
                  f"results: {d0} vs {d1}: {raw2[:300]}")
            return
        print(f"M2 upheld: identical entries -> identical results {d0}")

        # --- M3: per-entry limit independence (1 / 3 / 5) ---
        m3 = {"searches": [
            {"query": {"nearest": list(BLUE_VEC)}, "limit": 1},
            {"query": {"nearest": list(BLUE_VEC)}, "limit": 3},
            {"query": {"nearest": list(BLUE_VEC)}, "limit": 5},
        ]}
        s3, body3, raw3 = query_batch(coll, m3)
        print(f"\nM3 per-entry limits [1,3,5] -> status={s3}")
        print(f"raw: {raw3[:400]}")
        if guard("M3", s3, raw3) == "stop":
            return
        if not (200 <= s3 <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — M3: valid "
                  f"batch rejected with {s3}: {raw3[:300]}")
            return
        res3 = body3.get("result") if isinstance(body3, dict) else None
        if not isinstance(res3, list) or len(res3) != 3:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — M3: "
                  f"outer result len={len(res3) if isinstance(res3, list) else 'non-list'} "
                  f"(expected 3): {raw3[:300]}")
            return
        want = [1, 3, 5]
        for idx, w in enumerate(want):
            ii = entry_ids(res3[idx])
            if ii is None or len(ii) != w:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                      f"M3 result[{idx}]: per-entry limit bleed — expected "
                      f"EXACTLY {w} points, got "
                      f"{len(ii) if isinstance(ii, list) else ii}: "
                      f"{raw3[:300]}")
                return
        print("M3 upheld: per-entry limits honored independently (1/3/5)")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
