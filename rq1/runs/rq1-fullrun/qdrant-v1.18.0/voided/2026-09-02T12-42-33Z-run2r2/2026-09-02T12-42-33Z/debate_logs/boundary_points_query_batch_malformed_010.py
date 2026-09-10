#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_query_batch_malformed_010
# strategy: strategy7 malformed input / character fuzzing on the batch query
#           face — raw byte bodies via data= (bypassing client JSON
#           serialization); the same family was probed on discover+batch in
#           R37 — this is the query+batch face of the same shape
# endpoint: points+query+batch
# constraint_ids: qdrant_behavioral_points_query_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/batch-query
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — serde trusts the input
#            stream is legal JSON/Unicode; truncated bodies, NUL bytes and
#            lone surrogates must be answered 4xx, never 5xx/panic)
# exploration_target: novel_candidate
# shape_id: malformed_stream_charset
# shape_type: type_confusion
# generalized_from: R37 discover+batch malformed stream (same family, new face)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy7 malformed stream x
  qdrant_behavioral_points_query_batch_001 — raw-byte bodies straight to the
  wire (data=, never json=, so client-side serialization cannot veto the
  malformed input first) on a seeded EXISTING collection:
    G   valid body hand-built as bytes -> 200 outer len 1 (transport sanity)
    F1  truncated JSON   b'{"searches": [{'                      -> 4xx
    F2  trailing comma   b'{"searches": [E],}'                   -> 4xx
    F3  bare NUL byte    b'{"searches": [E\\x00-limit...]}'      -> 4xx
    F4  escaped NUL in filter key ("gr\\u0000p")                 -> judge*
    F5  lone UTF-16 surrogate in match value ("re\\ud800d")      -> judge*
    * judge faces: 4xx clean or 200 with well-defined filter semantics
      (empty/failed match); a 200 whose filter silently matched everything
      or a 5xx is the defect signal.
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
  resource x behavioral_points_query_batch_001 (resource_009); strategy7
  malformed stream x behavioral_points_query_batch_001 (this script)]
Oracle: G -> 200 with outer result len EXACTLY 1 (anything else = the raw
  transport is broken, later faces confounded -> SCRIPT_ERROR); F1/F2/F3 ->
  400/422 (any 2xx = Type1_IllegalSuccess: malformed stream silently
  accepted); F4/F5 -> 4xx or 200-with-0-points (filter semantics on a
  no-such-key/no-such-value match: empty result is the only defensible 200;
  200 with NON-empty points = Type4: the corrupted filter key/value matched
  real payload); any face 5xx with /healthz alive = Type3_RuntimeFailure;
  transport failure -> /healthz liveness re-check then SCRIPT_ERROR
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

VALID_RAW = b'{"searches": [{"query": {"order_by": {"key": "rank", ' \
            b'"direction": "asc"}}, "limit": 3}]}'

# (label, raw body bytes, expectation kind: "pos_guard" | "rej" | "judge")
FACES = [
    ("G valid raw body", VALID_RAW, "pos_guard"),
    ("F1 truncated JSON", b'{"searches": [{', "rej"),
    ("F2 trailing comma",
     b'{"searches": [{"query": {"order_by": {"key": "rank", '
     b'"direction": "asc"}}, "limit": 3}],}', "rej"),
    ("F3 bare NUL byte in limit",
     b'{"searches": [{"query": {"order_by": {"key": "rank", '
     b'"direction": "asc"}}, "limit": 3\x00}]}', "rej"),
    ("F4 JSON-escaped NUL in filter key",
     b'{"searches": [{"filter": {"must": [{"key": "gr\\u0000p", '
     b'"match": {"value": "red"}}]}, "limit": 20}]}', "judge"),
    ("F5 lone UTF-16 surrogate in match value",
     b'{"searches": [{"filter": {"must": [{"key": "grp", '
     b'"match": {"value": "re\\ud800d"}}]}, "limit": 20}]}', "judge"),
]


def safe_request(method, endpoint, json=None, timeout=60, params=None,
                 data=None):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text); transport failure -> (-1, err, err).
    data= carries RAW bytes straight to the wire (strategy-7 discipline:
    malformed streams must bypass client-side JSON serialization).
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(
            method=method, url=url, json=json, headers=headers,
            timeout=timeout, params=params, data=data,
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


def query_batch_raw(coll, raw_body, timeout=60):
    """points+query+batch face with a raw byte body."""
    return safe_request("POST", f"/collections/{coll}/points/query/batch",
                        data=raw_body, timeout=timeout)


def n_points(body):
    """point count of result[0] for a single-entry batch; None on mismatch."""
    if not isinstance(body, dict):
        return None
    res = body.get("result")
    if not isinstance(res, list) or len(res) != 1:
        return None
    elem = res[0]
    if not isinstance(elem, dict) or not isinstance(elem.get("points"), list):
        return None
    return len(elem["points"])


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpqb10" + tag

    ok, raw = setup(coll)
    if not ok:
        print(f"setup failed: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        for label, raw_body, expect in FACES:
            s, body, rraw = query_batch_raw(coll, raw_body)
            print(f"\n{label} -> status={s}")
            print(f"raw: {rraw[:400]}")
            if s == -1:
                alive, hs, hraw = healthz_alive()
                print(f"transport failure on {label} (healthz status={hs}: {hraw})")
                print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
                return
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — "
                          f"{label}: returned {s}: {rraw[:300]}")
                else:
                    print(f"VERDICT: SCRIPT_ERROR — {label} 5xx and healthz down")
                return

            if expect == "pos_guard":
                if not (200 <= s <= 299):
                    print(f"VERDICT: SCRIPT_ERROR — G guard: valid raw body "
                          f"returned {s}; raw transport broken, later faces "
                          f"confounded: {rraw[:200]}")
                    return
                n = n_points(body)
                if n is None or n != 3:
                    print(f"VERDICT: SCRIPT_ERROR — G guard: expected outer "
                          f"len 1 with 3 points, got {n}; confounded")
                    return
                print(f"G guard upheld: 200, 1 result, 3 points")

            elif expect == "rej":
                if 200 <= s <= 299:
                    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — "
                          f"{label}: malformed stream silently ACCEPTED with "
                          f"status {s}: {rraw[:300]}")
                    return
                if s in (400, 422):
                    print(f"{label}: {s} clean rejection")
                else:
                    print(f"NOTE (judge): {label} returned {s}; recorded "
                          f"for the judge")

            else:  # judge faces F4/F5
                if 200 <= s <= 299:
                    n = n_points(body)
                    if n is None:
                        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                              f"{label}: 200 but result not one element "
                              f"carrying a points array: {rraw[:300]}")
                        return
                    if n == 0:
                        print(f"{label}: judge-call face — 200 with 0 points "
                              f"(corrupted key/value matches nothing; "
                              f"well-defined empty filter semantics); "
                              f"recorded for the judge")
                    else:
                        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                              f"{label}: 200 with {n} points — the corrupted "
                              f"filter key/value MATCHED real payload "
                              f"(no payload key 'gr\\u0000p' / no value "
                              f"'re\\ud800d' exists): {rraw[:300]}")
                        return
                elif s in (400, 422):
                    print(f"{label}: judge-call face — {s} clean rejection; "
                          f"recorded for the judge")
                else:
                    print(f"NOTE (judge): {label} returned {s}; recorded "
                          f"for the judge")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
