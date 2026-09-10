#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_query_batch_resource_009
# strategy: strategy6 resource-limit/DoS attack on the batch dimension —
#           batch cardinality and per-entry extreme limit; strategy-6
#           convention (OPPOSITE of strategy-1): acceptance is NOT demanded,
#           only no-crash
# endpoint: points+query+batch
# constraint_ids: qdrant_behavioral_points_query_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/batch-query
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-07 (Resource Exhaustion — the doc states no maximum batch
#            size, so a spec-legal huge batch could preallocate per-query
#            state and OOM/panic; a per-entry INT_MAX limit could do the
#            same on the scoring path)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy6 batch-resource x qdrant_behavioral_points_query_batch_001
  — no documented maximum batch size exists, so spec-legal extreme batches
  must not crash (strategy-6 convention: 200-accept is NOT demanded; a clean
  4xx cap is equally fine; the defect signal is 5xx/OOM/panic/hang):
    R1 400-entry batch (3 canonical entry shapes cycled, each limit 3) on a
       seeded 9-point collection -> outer result len EXACTLY 400 if accepted.
    R2 single entry with limit=2147483647 (INT_MAX) -> <= 9 points if
       accepted, or a clean 4xx; no crash either way.
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
  behavioral_points_query_batch_001 (mixed_008); strategy6 batch-size
  resource x behavioral_points_query_batch_001 (this script); strategy7
  malformed stream x behavioral_points_query_batch_001 (malformed_010)]
Oracle: R1 -> 200 with outer result len EXACTLY 400 (wrong len = Type4
  _StateLogicViolation: N-in/N-out broken at scale) or a clean 400/422 cap
  (both acceptable; NO_DEFECT either way); R2 -> 200 with <= 9 points or a
  clean 4xx (both acceptable); for both legs: 5xx with /healthz alive, or a
  crash token (oom/out of memory/panic/capacity overflow/killed) in the
  body = Type3_RuntimeFailure; transport failure -> /healthz liveness
  re-check (alive = Type3 hang candidate, dead = SCRIPT_ERROR)
  (constraint qdrant_behavioral_points_query_batch_001).
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
import time
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
BLUE_VEC = [0.0, 1.0, 0.0, 0.0]
BATCH_N = 400
CRASH_TOKENS = ("oom", "out of memory", "panic", "capacity overflow",
                "killed", "allocation failed")


def safe_request(method, endpoint, json=None, timeout=180, params=None):
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


def canonical_entries():
    return [
        {"query": {"nearest": list(BLUE_VEC)}, "limit": 3},
        {"query": {"order_by": {"key": "rank", "direction": "asc"}},
         "limit": 3},
        {"filter": {"must": [{"key": "grp",
                              "match": {"value": "blue"}}]}, "limit": 3},
    ]


def crash_in(raw):
    low = str(raw).lower()
    return any(t in low for t in CRASH_TOKENS)


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpqb9" + tag

    ok, raw = setup(coll)
    if not ok:
        print(f"setup failed: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        # --- R1: 400-entry spec-legal batch ---
        cycle = canonical_entries()
        searches = [dict(cycle[i % 3]) for i in range(BATCH_N)]
        t0 = time.time()
        s, body, raw = safe_request(
            "POST", f"/collections/{coll}/points/query/batch",
            json={"searches": searches}, timeout=180)
        dt = time.time() - t0
        print(f"R1 {BATCH_N}-entry batch -> status={s} in {dt:.1f}s")
        print(f"raw: {raw[:400]}")
        if s == -1:
            alive, hs, hraw = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — R1: "
                      f"hang/transport failure on a spec-legal "
                      f"{BATCH_N}-entry batch while /healthz alive "
                      f"(healthz status={hs})")
            else:
                print(f"VERDICT: SCRIPT_ERROR — R1 transport failure and "
                      f"healthz down (healthz status={hs}: {hraw})")
            return
        if 500 <= s <= 599 or crash_in(raw):
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — R1: "
                      f"{BATCH_N}-entry batch returned {s}/crash tokens "
                      f"(no documented maximum batch size): {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — R1 5xx and healthz down")
            return
        if 200 <= s <= 299:
            res = body.get("result") if isinstance(body, dict) else None
            n = len(res) if isinstance(res, list) else None
            if n != BATCH_N:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                      f"R1: accepted the {BATCH_N}-entry batch but returned "
                      f"outer len {n} (N-in/N-out broken at scale): "
                      f"{raw[:300]}")
                return
            print(f"R1: accepted, outer len == {BATCH_N} (N-in/N-out upheld "
                  f"at scale)")
        elif s in (400, 422):
            print(f"R1: clean {s} cap on batch size (acceptable disposition; "
                  f"no documented maximum was promised)")
        else:
            print(f"NOTE (judge): R1 returned {s}; recorded for the judge")

        # --- R2: single entry with INT_MAX limit ---
        r2 = {"searches": [{"query": {"nearest": list(BLUE_VEC)},
                            "limit": 2147483647}]}
        s2, body2, raw2 = safe_request(
            "POST", f"/collections/{coll}/points/query/batch",
            json=r2, timeout=90)
        print(f"\nR2 single entry limit=INT_MAX -> status={s2}")
        print(f"raw: {raw2[:400]}")
        if s2 == -1:
            alive, hs, hraw = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — R2: "
                      f"hang/transport failure on INT_MAX limit while "
                      f"/healthz alive (healthz status={hs})")
            else:
                print(f"VERDICT: SCRIPT_ERROR — R2 transport failure and "
                      f"healthz down (healthz status={hs}: {hraw})")
            return
        if 500 <= s2 <= 599 or crash_in(raw2):
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — R2: "
                      f"INT_MAX limit returned {s2}/crash tokens: "
                      f"{raw2[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — R2 5xx and healthz down")
            return
        if 200 <= s2 <= 299:
            res2 = body2.get("result") if isinstance(body2, dict) else None
            if not isinstance(res2, list) or len(res2) != 1:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                      f"R2: 200 but outer result len "
                      f"{len(res2) if isinstance(res2, list) else 'non-list'} "
                      f"(expected 1): {raw2[:300]}")
                return
            elem = res2[0]
            npts = (len(elem.get("points"))
                    if isinstance(elem, dict)
                    and isinstance(elem.get("points"), list) else None)
            if npts is None:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                      f"R2: result element not carrying a points array: "
                      f"{raw2[:300]}")
                return
            if npts > N_SEED:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                      f"R2: INT_MAX limit returned {npts} points from a "
                      f"{N_SEED}-point collection: {raw2[:300]}")
                return
            print(f"R2: accepted with {npts} points (<= {N_SEED}; limit is an "
                  f"upper bound, returning fewer is legal)")
        elif s2 in (400, 422):
            print("R2: clean 4xx rejection of INT_MAX limit (acceptable "
                  f"disposition)")
        else:
            print(f"NOTE (judge): R2 returned {s2}; recorded for the judge")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
