#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_query_offset_huge_001
# strategy: strategy6 resource-limit / DoS attack x the large-offset
#           behavioral promise ("large offsets are legal but may degrade
#           performance; slowness is documented, not a defect") — legal
#           extreme offsets must answer 200-empty without crashing, and
#           the offset x limit product must not preallocate the server
#           into OOM
# endpoint: points+query
# constraint_ids: qdrant_behavioral_points_query_002, qdrant_range_points_query_001
# source_url: https://qdrant.tech/documentation/search/search/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-07 (Resource Exhaustion — an offset far beyond the stored
#            count is a legal u64; if the implementation materializes
#            offset+limit slots or iterates the segment, a single request
#            OOMs or hangs the service)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy6 resource x qdrant_behavioral_points_query_002 — the
  contract explicitly permits large offsets ("large offsets are legal but
  may degrade performance; slowness is documented"). The attack verifies
  the RESOURCE face of that permission on a 12-point seeded collection
  (dim 4, Euclid): every huge offset is a LEGAL value (min 0, no
  documented max), so the only defect classes are crash-shaped:
    Hc   offset=0 (healthy control)             -> 200 with 5 points
    H1   offset=100000 (5 orders beyond the     -> 200 with 0 points, no
         stored count)                             next_page_offset
    H2   offset=2147483647 (i32 INT_MAX)        -> 200 with 0 points
    H3   offset=18446744073709551615 (u64 MAX)  -> 200 with 0 points OR a
                                                   clean 4xx (both legal
                                                   faces; only crash is a
                                                   defect)
    H4   offset=100000 x limit=999999999 (the  -> 200 with 0 points (the
         product face: allocator preallocation    product must not be
         probe)                                    materialized into OOM)
  Requests carry a 120s timeout; per the promise, SLOWNESS ALONE IS NOT A
  DEFECT (printed as an observation), but a timeout/connection error with
  /healthz still alive, or any 5xx with /healthz alive, is Type3.
  [chunk_points+query coverage: strategy1+6 limit x range_points_query_001
  (limit_001); strategy1 offset x range_points_query_001 (offset_001);
  strategy1 hnsw_ef x range_points_query_002 (hnswef_001); strategy1
  acorn_scale x range_points_query_002 (acorn_001); strategy2 oneOf-domain
  negative x type_points_query_001 (variant_type_001); strategy2 oneOf-domain
  positive closure x type_points_query_001 (variant_matrix_001); strategy2
  invalid-query/filter + 404 x behavioral_points_query_001 (envelope_001);
  strategy7 malformed stream x behavioral_points_query_001 (malformed_001);
  strategy3 by-id vector characteristic mismatch x state_points_query_001
  (byid_dim_001); state by-id missing-point x state_points_query_001
  (byid_stale_001); strategy1 query-absent id-order x
  behavioral_points_query_004 (noid_order_001); strategy1 exact=true
  pagination stability x behavioral_points_query_003 (offset_exact_001);
  strategy6 huge-offset resource x behavioral_points_query_002
  (this script)]
Oracle: Hc -> 200 with exactly 5 points; H1/H2/H4 -> 200 with 0 points
  and no next_page_offset (200 with > 0 points = Type4_StateLogicViolation:
  points materialized from beyond the stored count); H3 -> 200-empty or a
  clean 400/422 (both reported as conformant; 200-with-points =
  Type4_StateLogicViolation); any 5xx with /healthz alive =
  Type3_RuntimeFailure (OOM/DoS — the resource defect class); a request
  timeout / connection error with /healthz alive = Type3_RuntimeFailure
  (hang), with /healthz dead = SCRIPT_ERROR; per the contract SLOW 200s
  are NOT defects (latency printed as observation only) (constraints
  qdrant_behavioral_points_query_002 + qdrant_range_points_query_001).
Constraint: qdrant_behavioral_points_query_002 (bare id) — "large offsets
  are legal but may degrade performance; slowness on large offsets is
  documented, not a defect" (evidence_tier: explicit; level: endpoint)

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
N_SEED = 12
V = [0.5, 0.25, 0.125, 0.0625]


def safe_request(method, endpoint, json=None, timeout=60, params=None):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text); transport failure -> (-1, err, err).
    Query params (wait/consistency) via params= — never stuffed into the body.
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


def extract_next_offset(body):
    """next_page_offset lives in the result object (contract: next_page_offset?)."""
    result = body.get("result") if isinstance(body, dict) else None
    if isinstance(result, dict):
        return result.get("next_page_offset")
    if isinstance(result, list):
        return body.get("next_page_offset")
    return None


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpqH1" + tag

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

        # (label, offset, limit, expectation) — expectation: 'empty' (200 + 0
        # points) or 'control' (200 + 5 points) or 'empty-or-4xx' (u64 max)
        legs = (
            ("Hc offset=0 (healthy control)", 0, 5, "control"),
            ("H1 offset=100000", 100000, 5, "empty"),
            ("H2 offset=2147483647 (i32 INT_MAX)", 2147483647, 5, "empty"),
            ("H3 offset=18446744073709551615 (u64 MAX)", 18446744073709551615, 5, "empty-or-4xx"),
            ("H4 offset=100000 x limit=999999999 (product probe)", 100000, 999999999, "empty"),
        )

        for label, off, lim, expect in legs:
            t0 = time.time()
            s, b, raw = safe_request("POST", f"/collections/{coll}/points/query",
                                     json={"query": {"nearest": V}, "limit": lim,
                                           "offset": off}, timeout=120)
            dt = time.time() - t0
            print(f"\nleg {label} -> status={s} ({dt:.2f}s; slow 200s are documented "
                  f"non-defects, latency printed as observation only)")
            print(f"raw: {raw[:400]}")
            if s == -1:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: "
                          f"request did not complete (transport error/timeout) while "
                          f"/healthz is alive (hang/DoS signal on a legal offset): "
                          f"{raw[:200]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — transport failure and healthz down")
                return
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: "
                          f"legal offset returned {s} with service alive (OOM/DoS — the "
                          f"contract permits slow answers, not crashes): {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return
            if expect == "empty-or-4xx":
                if s in (400, 422):
                    print(f"leg {label} OK: clean {s} rejection (u64-max face, legal "
                          f"disposition)")
                    continue
            pts_a, shape = extract_points(b)
            if s != 200 or pts_a is None:
                if s in (400, 422):
                    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{label}]: "
                          f"offset={off} is inside the documented domain (min 0, no max; "
                          f"'large offsets are legal'), but the request was rejected with "
                          f"{s}: {raw[:300]}")
                else:
                    print(f"VERDICT: SCRIPT_ERROR — unexpected status/envelope {s} ({shape}); "
                          f"no defect conclusion")
                return
            n = len(pts_a)
            if expect == "control":
                if n != 5:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg "
                          f"[{label}]: control page must hold 5 points, got {n}: {raw[:300]}")
                    return
                print(f"leg {label} OK: 200 with {n} points (control, envelope {shape})")
            else:
                if n != 0:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg "
                          f"[{label}]: only {N_SEED} points are stored, offset={off} is "
                          f"beyond them, yet {n} points were materialized: ids "
                          f"{[p.get('id') for p in pts_a][:10]}: {raw[:300]}")
                    return
                npo = extract_next_offset(b)
                if npo is not None:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg "
                          f"[{label}]: empty terminal page still advertises "
                          f"next_page_offset={npo!r}: {raw[:200]}")
                    return
                print(f"leg {label} OK: 200 with 0 points, no next_page_offset "
                      f"(envelope {shape})")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
