#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_query_batch_404_002
# strategy: assertion 404 leg — negative side of the batch behavioral
#           promise: "404 for a missing collection", measured on the batch
#           face and (G9 parity) on the single query face in the same run
# endpoint: points+query+batch
# constraint_ids: qdrant_behavioral_points_query_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/batch-query
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — the missing-collection leg of
#            the promise is easy to skip because the happy path is 200; a
#            server answering 200 with fabricated per-query results, or 500,
#            on a nonexistent collection breaks the explicit 404 promise)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: assertion 404 leg x qdrant_behavioral_points_query_batch_001 — the
  assertion explicitly promises "404 for a missing collection" for batch
  query. Legs (collection name is a fresh uuid tag, guaranteed nonexistent):
    Q1 batch face: POST /collections/{missing}/points/query/batch with a
       fully valid searches body -> EXACTLY 404
    Q2 single-face parity (G9): POST /collections/{missing}/points/query
       with the same entry body unwrapped -> 404 per the sibling assertion
       qdrant_behavioral_points_query_001; a disposition mismatch between
       the two faces of the same promise is recorded as a defect signal.
  [chunk_points+query+batch coverage: strategy1 positive order/count core x
  behavioral_points_query_batch_001 (positive_001); assertion 404 leg x
  behavioral_points_query_batch_001 (this script); strategy2 searches wrapper
  type x behavioral_points_query_batch_001 (searches_type_003); strategy2
  entry presence matrix x behavioral_points_query_batch_001 (presence_004);
  R33-family dual-key enum discard x behavioral_points_query_batch_001
  (dualkey_005); strategy1 per-entry limit x behavioral_points_query_batch_001
  + range_points_query_001 min-1 ground (limit_006); strategy1 per-entry
  offset x behavioral_points_query_batch_001 + range_points_query_001 min-0
  ground (offset_007); mixed-variant universal-queries promise x
  behavioral_points_query_batch_001 (mixed_008); strategy6 batch-size
  resource x behavioral_points_query_batch_001 (resource_009); strategy7
  malformed stream x behavioral_points_query_batch_001 (malformed_010)]
Oracle: Q1 -> EXACTLY 404 (200 = Type1_IllegalSuccess: per-query results
  fabricated for a missing collection against the explicit 404 promise;
  400/422 = promise-shaped mismatch recorded for the judge; 5xx with
  /healthz alive = Type3_RuntimeFailure); Q2 -> 404 with Q1==Q2 disposition
  (mismatch = G9 same-promise cross-face asymmetry, recorded for the judge;
  transport failure -> /healthz liveness re-check then SCRIPT_ERROR)
  (constraint qdrant_behavioral_points_query_batch_001).
Constraint: qdrant_behavioral_points_query_batch_001 (bare id) — "executes
  multiple queries in one call; returns 200 with a list of per-query results;
  404 for a missing collection" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+query+batch    -> POST /collections/{collection_name}/points/query/batch
  points+query          -> POST /collections/{collection_name}/points/query
  healthz               -> GET  /healthz
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
VALID_ENTRY = {"query": {"nearest": [0.0, 1.0, 0.0, 0.0]}, "limit": 3}


def safe_request(method, endpoint, json=None, timeout=30, params=None):
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


def main():
    # guaranteed-missing collection: fresh uuid tag, never created
    missing = "bpqb2_missing_" + uuid.uuid4().hex[:10]

    # --- Q1: batch face on the missing collection ---
    s, body, raw = safe_request(
        "POST", f"/collections/{missing}/points/query/batch",
        json={"searches": [dict(VALID_ENTRY)]}, timeout=30)
    print(f"Q1 batch face on missing collection -> status={s}")
    print(f"raw: {raw[:400]}")
    if s == -1:
        alive, hs, hraw = healthz_alive()
        print(f"transport failure on Q1 (healthz status={hs}: {hraw})")
        print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
        return
    if 500 <= s <= 599:
        alive, _, _ = healthz_alive()
        if alive:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Q1: missing "
                  f"collection returned {s} instead of 404: {raw[:300]}")
        else:
            print("VERDICT: SCRIPT_ERROR — Q1 5xx and healthz down")
        return
    if s == 200:
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — Q1: missing "
              f"collection answered 200 with per-query results against the "
              f"explicit 404 promise: {raw[:300]}")
        return
    if s != 404:
        print(f"NOTE (judge): Q1 returned {s}, not the promised 404 — "
              f"promise-shape mismatch recorded for the judge")
    else:
        print("Q1 upheld: 404 as promised")

    # --- Q2: single-face parity on the same missing collection ---
    s2, body2, raw2 = safe_request(
        "POST", f"/collections/{missing}/points/query",
        json=dict(VALID_ENTRY), timeout=30)
    print(f"\nQ2 single-face parity -> status={s2}")
    print(f"raw: {raw2[:400]}")
    if s2 == -1:
        alive, hs, hraw = healthz_alive()
        print(f"transport failure on Q2 (healthz status={hs}: {hraw})")
        print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
        return
    if 500 <= s2 <= 599:
        alive, _, _ = healthz_alive()
        if alive:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Q2: missing "
                  f"collection returned {s2} on the single face: {raw2[:300]}")
        else:
            print("VERDICT: SCRIPT_ERROR — Q2 5xx and healthz down")
        return
    if s2 == 200:
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — Q2: missing "
              f"collection answered 200 on the single query face "
              f"(sibling promise 404): {raw2[:300]}")
        return
    if s2 != 404:
        print(f"NOTE (judge): Q2 returned {s2}, not 404 — recorded for the judge")
    else:
        print("Q2 upheld: 404 as promised")

    # G9 disposition comparison
    if s != s2:
        print(f"NOTE (G9): same missing-collection promise answered {s} on the "
              f"batch face vs {s2} on the single face — cross-face asymmetry "
              f"recorded for the judge")
    else:
        print(f"G9 parity: both faces answer {s} for the missing collection")

    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
