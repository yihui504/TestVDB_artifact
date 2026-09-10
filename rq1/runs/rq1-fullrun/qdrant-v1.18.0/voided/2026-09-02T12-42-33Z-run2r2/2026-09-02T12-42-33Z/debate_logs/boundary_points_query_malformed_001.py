#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_query_malformed_001
# strategy: strategy7 malformed input / character fuzzing on the query
#           face's request stream (malformed JSON, NUL bytes, lone
#           surrogate, empty body) — dual defect classes Type3 (5xx) and
#           Type1 (silent accept), with an interleaved valid leg proving
#           the face stays live between probes
# endpoint: points+query
# constraint_ids: qdrant_behavioral_points_query_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Coercion Trust — the parser is assumed to
#            reject malformed streams cleanly; serde/unicode edge cases
#            that panic or leak internal errors surface as 5xx)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy7 malformed-stream x qdrant_behavioral_points_query_001 —
  the "invalid query returns 400" face is fed structurally-invalid REQUEST
  STREAMS (not merely invalid field values) on a 6-point seeded collection
  (dim 4, Euclid). All probes are sent as raw bytes via data= so the
  server-side parser is exercised directly (client JSON serialization is
  bypassed):
    F0   valid body (control)               -> 200 with points (face live)
    F1   truncated JSON (no closing brace)  -> 400 (clean parse rejection)
    F2   trailing comma                     -> 400
    F3   raw NUL byte inside a filter key   -> 400 (no 5xx, no truncation)
    F4   escaped lone surrogate \\uD800 in   -> 400 or clean handling (not
         a filter key                          legal Unicode; 5xx = defect)
    F5   empty body                         -> 400
    F6   valid body again (liveness        -> 200 with points (G8
         re-check after the barrage)          isolation: probe damage
                                               must not leak forward)
  [chunk_points+query coverage: strategy1+6 limit x range_points_query_001
  (limit_001); strategy1 offset x range_points_query_001 (offset_001);
  strategy1 hnsw_ef x range_points_query_002 (hnswef_001); strategy1
  acorn_scale x range_points_query_002 (acorn_001); strategy2 oneOf-domain
  negative x type_points_query_001 (variant_type_001); strategy2 oneOf-domain
  positive closure x type_points_query_001 (variant_matrix_001); strategy2
  invalid-query/filter + 404 x behavioral_points_query_001 (envelope_001);
  strategy7 malformed stream x behavioral_points_query_001 (this script);
  strategy3 by-id vector characteristic mismatch x state_points_query_001
  (byid_dim_001); state by-id missing-point x state_points_query_001
  (byid_stale_001); strategy1 query-absent id-order x
  behavioral_points_query_004 (noid_order_001); strategy1 exact=true
  pagination stability x behavioral_points_query_003 (offset_exact_001);
  strategy6 huge-offset resource x behavioral_points_query_002
  (offset_huge_001)]
Oracle: F0/F6 -> 200 with a non-empty points array; F1..F5 -> 400 or 422
  clean rejection (any 5xx with /healthz alive = Type3_RuntimeFailure —
  the DB must robustly 4xx illegal input streams, not crash; any 2xx on a
  syntactically invalid stream = Type1_IllegalSuccess flagged for
  judge-doc adjudication; transport failure -> /healthz re-check then
  SCRIPT_ERROR) (constraint qdrant_behavioral_points_query_001).
Constraint: qdrant_behavioral_points_query_001 (bare id) — "returns 200
  QueryResponse {result: [ScoredPoint], next_page_offset?}; 400 on an
  invalid query; 404 when the collection is missing" (evidence_tier:
  explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+query        -> POST /collections/{collection_name}/points/query
  points+upsert       -> PUT  /collections/{collection_name}/points
  collections+create  -> PUT  /collections/{collection_name}
  collections+delete  -> DELETE /collections/{collection_name}
  healthz             -> GET  /healthz
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
N_SEED = 6
V = [0.5, 0.25, 0.125, 0.0625]


def safe_request(method, endpoint, json=None, timeout=60, params=None, data=None):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text); transport failure -> (-1, err, err).
    Query params via params=; raw body streams via data= (bytes) so
    malformed probes reach the server parser without client-side
    serialization rejecting them first.
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


def extract_points(body):
    """
    Locate the ScoredPoint array in the QueryResponse envelope.
    Contract response_shape: result (object) -> result.points (array).
    A legacy list-form result is tolerated and reported (shape oracles
    cross-checked against the published OpenAPI — standing lesson).
    """
    if not isinstance(body, dict):
        return None, "body-not-dict"
    result = body.get("result")
    if isinstance(result, dict):
        pts = result.get("points")
        return (pts if isinstance(pts, list) else None), "result.points"
    if isinstance(result, list):
        return result, "result-array-observed"
    return None, "result-missing"


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpqF1" + tag

    # Arrange: own collection, own data, own cleanup
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        pts = [{"id": i, "vector": [v * (1.0 + i / 100.0) for v in V]} for i in range(1, N_SEED + 1)]
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": pts}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return

        VALID = json.dumps({"query": {"nearest": V}, "limit": 3}).encode("utf-8")
        # Raw probe bodies (bytes; \x00 is a REAL NUL byte, \\uD800 an escaped lone surrogate)
        probes = (
            ("F0 valid control", VALID, "ok"),
            ("F1 truncated JSON",
             b'{"query": {"nearest": [0.5, 0.25, 0.125, 0.0625', "reject"),
            ("F2 trailing comma",
             b'{"query": {"nearest": [0.5, 0.25, 0.125, 0.0625]}, "limit": 3,}', "reject"),
            ("F3 raw NUL in filter key",
             b'{"query": {"nearest": [0.5, 0.25, 0.125, 0.0625]}, "limit": 3, '
             b'"filter": {"must": [{"key": "ci\x00ty", "match": {"value": "x"}}]}}',
             "reject"),
            ("F4 escaped lone surrogate in key",
             b'{"query": {"nearest": [0.5, 0.25, 0.125, 0.0625]}, "limit": 3, '
             b'"filter": {"must": [{"key": "ci\\uD800ty", "match": {"value": "x"}}]}}',
             "reject"),
            ("F5 empty body", b"", "reject"),
            ("F6 valid control (post-barrage liveness)", VALID, "ok"),
        )

        for label, raw_body, expect in probes:
            s, b, raw = safe_request("POST", f"/collections/{coll}/points/query",
                                     data=raw_body, timeout=60)
            print(f"\n{label} -> status={s}")
            print(f"body bytes: {raw_body[:110]!r}")
            print(f"raw: {raw[:400]}")
            if s == -1:
                alive, _, _ = healthz_alive()
                print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion" if alive else
                      "VERDICT: SCRIPT_ERROR — transport failure and healthz down")
                return
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — [{label}]: malformed "
                          f"input stream returned {s} with service alive (the DB must 4xx "
                          f"illegal input, not crash): {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return
            lowered = raw.lower()
            if 500 <= s or any(k in lowered for k in
                               ("panic", "internal error", "serde", "utf-8", "decode error")):
                # defensive double-check on 4xx bodies leaking parser internals
                if "panic" in lowered or "internal error" in lowered:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — [{label}]: parser "
                          f"internal error leakage in a {s} body: {raw[:300]}")
                    return
            if expect == "ok":
                pts_a, shape = extract_points(b)
                if s != 200 or pts_a is None or len(pts_a) < 1:
                    print(f"VERDICT: SCRIPT_ERROR — control [{label}] did not return a live "
                          f"200 face (status={s}); no defect conclusion")
                    return
                print(f"{label} OK: 200 with {len(pts_a)} points (envelope {shape})")
            else:
                if s in (200, 201, 202):
                    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — [{label}]: a "
                          f"syntactically invalid request stream was ACCEPTED with {s} "
                          f"(pending judge-doc verification of stream-level semantics): "
                          f"{raw[:300]}")
                    return
                if s not in (400, 422):
                    print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on [{label}]; no defect conclusion")
                    return
                print(f"{label} OK: clean rejection with {s}")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
