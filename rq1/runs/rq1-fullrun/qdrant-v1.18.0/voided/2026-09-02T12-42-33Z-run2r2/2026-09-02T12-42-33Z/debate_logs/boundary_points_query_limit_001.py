#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_query_limit_001
# strategy: strategy1 boundary-value attack on the limit parameter of the
#           universal query API (min-1 promise + default-10 promise +
#           strategy6 resource leg for the extreme value)
# endpoint: points+query
# constraint_ids: qdrant_range_points_query_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — clients trust limit>=1 is
#            enforced and that omitting limit yields the documented default
#            of 10; a server accepting limit=0/-1 or defaulting differently
#            breaks pagination arithmetic silently)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary x qdrant_range_points_query_001 — the contract
  asserts "limit minimum 1 (default 10)" on POST /collections/{c}/points/
  query. Boundary matrix on a 12-point seeded collection (dim 4, Euclid,
  binary-exact floats so stored == submitted):
    L1    limit=1 (min legal closure)      -> 200, EXACTLY 1 point,
                                             next_page_offset == 1 (0+1)
    Ldef  limit omitted (default leg)      -> 200, EXACTLY 10 points
                                             (default 10), next_page_offset
                                             == 10 (0+10)
    L0    limit=0 (min-1 boundary)         -> 400/422 reject
    Lneg  limit=-1 (negative boundary)     -> 400/422 reject
    Ltype limit="5" (string, strategy2     -> 400/422 reject
          cross-leg)
    Lext  limit=999999999 (strategy6       -> 200 with <= 12 points and NO
          resource leg)                       crash (limit is an upper
                                             bound; returning fewer is
                                             legal; 5xx/OOM = Type3)
  [chunk_points+query coverage: strategy1+6 limit x range_points_query_001
  (this script); strategy1 offset x range_points_query_001
  (offset_001); strategy1 hnsw_ef x range_points_query_002 (hnswef_001);
  strategy1 acorn_scale x range_points_query_002 (acorn_001); strategy2
  oneOf-domain negative x type_points_query_001 (variant_type_001);
  strategy2 oneOf-domain positive closure x type_points_query_001
  (variant_matrix_001); strategy2 invalid-query/filter + 404 x
  behavioral_points_query_001 (envelope_001); strategy7 malformed stream x
  behavioral_points_query_001 (malformed_001); strategy3 by-id vector
  characteristic mismatch x state_points_query_001 (byid_dim_001); state
  by-id missing-point x state_points_query_001 (byid_stale_001); strategy1
  query-absent id-order x behavioral_points_query_004 (noid_order_001);
  strategy1 exact=true pagination stability x behavioral_points_query_003
  (offset_exact_001); strategy6 huge-offset resource x
  behavioral_points_query_002 (offset_huge_001)]
Oracle: L1 -> 200 with exactly 1 ScoredPoint and next_page_offset == 1;
  Ldef -> 200 with exactly 10 ScoredPoints and next_page_offset == 10
  (arithmetic-derived: offset default 0 + limit; count mismatch or absent
  next_page_offset while >= 1 result remains = Type4_StateLogicViolation);
  L0/Lneg/Ltype -> 400 or 422 (200 = Type1_IllegalSuccess: min-1 promise
  violated); Lext -> 200 with <= 12 points and no 5xx (5xx with /healthz
  alive = Type3_RuntimeFailure; transport error with /healthz alive =
  Type3 hang, dead = SCRIPT_ERROR); 4xx on L1/Ldef = Type1_IllegalSuccess
  (valid documented request rejected) (constraint qdrant_range_points_query_001).
Constraint: qdrant_range_points_query_001 (bare id) — "limit minimum 1
  (default 10); offset minimum 0 (default 0)" (evidence_tier: explicit;
  level: endpoint)

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
N_SEED = 12
# binary-exact floats: stored == submitted under Euclid (no normalization — R27)
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
    A legacy list-form result is tolerated and reported so the observed
    envelope shape reaches the judge (shape oracles cross-checked against
    the published OpenAPI — standing lesson).
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
    coll = "bpqL1" + tag

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

        # ---- Leg L1: limit=1 (min legal closure) ----
        s, b, raw = safe_request("POST", f"/collections/{coll}/points/query",
                                 json={"query": {"nearest": V}, "limit": 1}, timeout=60)
        print(f"\nleg L1 limit=1 -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            alive, _, _ = healthz_alive()
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion" if alive else
                  "VERDICT: SCRIPT_ERROR — transport failure and healthz down")
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [L1 limit=1]: valid "
                      f"query returned {s} with service alive: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
            return
        pts_a, shape = extract_points(b)
        if s in (400, 404, 422):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [L1 limit=1]: min-closure "
                  f"limit=1 is a documented legal value but got {s}: {raw[:300]}")
            return
        if s != 200 or pts_a is None:
            print(f"VERDICT: SCRIPT_ERROR — unexpected status/envelope {s} ({shape}); no defect conclusion")
            return
        if len(pts_a) != 1:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [L1 limit=1]: limit=1 "
                  f"must return exactly 1 point, got {len(pts_a)}: {raw[:300]}")
            return
        npo = extract_next_offset(b)
        if npo != 1:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [L1 limit=1]: with "
                  f"{N_SEED} seeded points and offset default 0, next_page_offset must be 1, "
                  f"got {npo!r}: {raw[:300]}")
            return
        print(f"leg L1 OK: exactly 1 point, next_page_offset=1 (envelope {shape})")

        # ---- Leg Ldef: limit omitted (default 10 promise) ----
        s, b, raw = safe_request("POST", f"/collections/{coll}/points/query",
                                 json={"query": {"nearest": V}}, timeout=60)
        print(f"\nleg Ldef limit-omitted -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            alive, _, _ = healthz_alive()
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion" if alive else
                  "VERDICT: SCRIPT_ERROR — transport failure and healthz down")
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [Ldef]: valid query "
                      f"returned {s} with service alive: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
            return
        pts_a, shape = extract_points(b)
        if s != 200 or pts_a is None:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [Ldef]: default-limit "
                  f"query rejected/malformed with {s}: {raw[:300]}")
            return
        if len(pts_a) != 10:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [Ldef]: documented "
                  f"default limit is 10 with {N_SEED} points available, got {len(pts_a)} points: "
                  f"{raw[:300]}")
            return
        npo = extract_next_offset(b)
        if npo != 10:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [Ldef]: 10 of "
                  f"{N_SEED} shown from offset 0, next_page_offset must be 10, got {npo!r}: "
                  f"{raw[:300]}")
            return
        print("leg Ldef OK: default limit 10 honored, next_page_offset=10")

        # ---- Negative legs: L0 / Lneg / Ltype -> must be rejected ----
        for label, lim in (("L0 limit=0", 0), ("Lneg limit=-1", -1), ("Ltype limit='5'", "5")):
            s, b, raw = safe_request("POST", f"/collections/{coll}/points/query",
                                     json={"query": {"nearest": V}, "limit": lim}, timeout=60)
            print(f"\nleg {label} -> status={s}")
            print(f"raw: {raw[:400]}")
            if s == -1:
                alive, _, _ = healthz_alive()
                print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion" if alive else
                      "VERDICT: SCRIPT_ERROR — transport failure and healthz down")
                return
            if 500 <= s <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: illegal "
                          f"limit returned {s} (must be a clean 4xx) with service alive: {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return
            if s == 200:
                n = len(extract_points(b)[0] or [])
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{label}]: contract "
                      f"asserts limit minimum 1, but the request was ACCEPTED with 200 "
                      f"({n} points returned): {raw[:300]}")
                return
            if s not in (400, 422):
                print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on leg [{label}]; no defect conclusion")
                return
            # Type2 observation only (R29: error-naming carries no verdict weight)
            named = "limit" in raw.lower()
            print(f"leg {label} OK: rejected with {s} (error names 'limit': {named})")

        # ---- Leg Lext: limit=999999999 (strategy6 resource) ----
        s, b, raw = safe_request("POST", f"/collections/{coll}/points/query",
                                 json={"query": {"nearest": V}, "limit": 999999999}, timeout=120)
        print(f"\nleg Lext limit=999999999 -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            alive, _, _ = healthz_alive()
            if alive:
                print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [Lext]: request did not "
                      "complete (transport error) while /healthz is alive (hang/DoS signal)")
            else:
                print("VERDICT: SCRIPT_ERROR — transport failure and healthz down")
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [Lext]: huge limit "
                      f"returned {s} with service alive (OOM/DoS): {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
            return
        if s == 200:
            pts_a, _ = extract_points(b)
            n = len(pts_a) if pts_a is not None else -1
            if pts_a is None:
                print(f"VERDICT: SCRIPT_ERROR — 200 but no points array on Lext; no defect conclusion")
                return
            if n > N_SEED:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [Lext]: only "
                      f"{N_SEED} points exist but {n} returned: {raw[:300]}")
                return
            print(f"leg Lext OK: 200 with {n} <= {N_SEED} points (upper-bound semantics, no crash)")
        elif s in (400, 422):
            print(f"leg Lext OK: clean {s} rejection (resource-class norm)")
        else:
            print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on Lext; no defect conclusion")
            return

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
