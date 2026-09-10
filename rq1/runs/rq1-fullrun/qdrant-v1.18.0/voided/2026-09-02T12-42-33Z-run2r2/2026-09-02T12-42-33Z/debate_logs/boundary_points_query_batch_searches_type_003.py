#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_query_batch_searches_type_003
# strategy: strategy2 type-boundary attack on the searches wrapper — the one
#           required body field (request_required_paths lists "searches") is
#           fed every wrong shape; the promise "returns 200 with a list of
#           per-query results" cannot license any of these
# endpoint: points+query+batch
# constraint_ids: qdrant_behavioral_points_query_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/batch-query
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — the wrapper could be
#            coerced: missing/null searches treated as an empty batch,
#            object/string scalars iterated as one entry, null entries
#            skipped silently; all accepted with 200 = undefined behavior)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 wrapper type confusion x
  qdrant_behavioral_points_query_batch_001 on an EXISTING seeded collection
  (isolates wrapper validation from the 404 leg):
    W1 searches missing (empty body {})          -> reject
    W2 searches=null                             -> reject
    W3 searches={} (object, not array)           -> reject
    W4 searches=42 (scalar int)                  -> reject
    W5 searches=[null] (null element)            -> reject
    W6 searches="abc" (string)                   -> reject
  [chunk_points+query+batch coverage: strategy1 positive order/count core x
  behavioral_points_query_batch_001 (positive_001); assertion 404 leg x
  behavioral_points_query_batch_001 (404_002); strategy2 searches wrapper
  type x behavioral_points_query_batch_001 (this script); strategy2
  entry presence matrix x behavioral_points_query_batch_001 (presence_004);
  R33-family dual-key enum discard x behavioral_points_query_batch_001
  (dualkey_005); strategy1 per-entry limit x behavioral_points_query_batch_001
  + range_points_query_001 min-1 ground (limit_006); strategy1 per-entry
  offset x behavioral_points_query_batch_001 + range_points_query_001 min-0
  ground (offset_007); mixed-variant universal-queries promise x
  behavioral_points_query_batch_001 (mixed_008); strategy6 batch-size
  resource x behavioral_points_query_batch_001 (resource_009); strategy7
  malformed stream x behavioral_points_query_batch_001 (malformed_010)]
Oracle: W1-W6 -> 400 or 422 (any 2xx = Type1_IllegalSuccess: the required
  searches field absent or type-broken yet the batch "succeeds" — the
  one-result-per-search promise cannot be satisfied by a non-array wrapper;
  200 with an empty result on W1/W2 would additionally contradict the
  wrapper's required status per request_required_paths); 5xx with /healthz
  alive = Type3_RuntimeFailure; transport failure -> /healthz liveness
  re-check then SCRIPT_ERROR (constraint
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

VALID_ENTRY = {"query": {"nearest": [0.0, 1.0, 0.0, 0.0]}, "limit": 3}

# (label, body dict, expectation kind: "rej")
FACES = [
    ("W1 searches missing", {}, "rej"),
    ("W2 searches=null", {"searches": None}, "rej"),
    ("W3 searches={} (object)", {"searches": {}}, "rej"),
    ("W4 searches=42 (scalar int)", {"searches": 42}, "rej"),
    ("W5 searches=[null] (null element)", {"searches": [None]}, "rej"),
    ("W6 searches=\"abc\" (string)", {"searches": "abc"}, "rej"),
]


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


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpqb3" + tag

    ok, raw = setup(coll)
    if not ok:
        print(f"setup failed: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        # G guard: sanity — the valid wrapper on this collection succeeds
        gs, _, graw = safe_request(
            "POST", f"/collections/{coll}/points/query/batch",
            json={"searches": [dict(VALID_ENTRY)]}, timeout=60)
        print(f"G valid-wrapper guard -> status={gs}")
        print(f"raw: {graw[:300]}")
        if not (200 <= gs <= 299):
            print(f"NOTE (judge): valid wrapper guard returned {gs} — "
                  f"rejections below are confounded; recorded for the judge")

        for label, body_, expect in FACES:
            s, body, raw = safe_request(
                "POST", f"/collections/{coll}/points/query/batch",
                json=body_, timeout=60)
            print(f"\n{label} -> status={s}")
            print(f"raw: {raw[:400]}")
            if s == -1:
                alive, hs, hraw = healthz_alive()
                print(f"transport failure on {label} (healthz status={hs}: {hraw})")
                print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
                return
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — "
                          f"{label}: returned {s}: {raw[:300]}")
                else:
                    print(f"VERDICT: SCRIPT_ERROR — {label} 5xx and healthz down")
                return
            if 200 <= s <= 299:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label}: "
                      f"broken/absent required searches wrapper ACCEPTED with "
                      f"status {s} (request_required_paths: searches; the "
                      f"one-result-per-search promise cannot hold): "
                      f"{raw[:300]}")
                return
            if s in (400, 422):
                low = raw.lower()
                named = any(t in low for t in ("searches", "query", "required",
                                               "missing", "invalid", "expected"))
                note = ("diagnostics name the wrapper construct"
                        if named else
                        "NOTE (strategy5): rejection text names no wrapper "
                        "token — diagnostics gap recorded for the judge")
                print(f"{label}: {s} clean rejection; {note}")
            else:
                print(f"NOTE (judge): {label} returned {s}; recorded for the judge")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
