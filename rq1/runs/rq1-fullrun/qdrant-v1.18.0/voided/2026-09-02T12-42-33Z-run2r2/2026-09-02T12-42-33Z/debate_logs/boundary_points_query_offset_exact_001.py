#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_query_offset_exact_001
# strategy: strategy1/semantic attack on the exact=true pagination
#           stability promise — walking all pages via next_page_offset
#           under exact search must PARTITION the stored id set (no
#           duplicates, no skips); the plain-HNSW walk is by-design exempt
#           (threat model #9523) and only structurally checked
# endpoint: points+query
# constraint_ids: qdrant_behavioral_points_query_003
# source_url: https://qdrant.tech/documentation/search/search/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-05 (semantic drift — exact=true is the documented escape
#            hatch that makes offset pagination deterministic; if the
#            escape hatch silently behaves like approximate HNSW, every
#            client paginating under exact=true double-counts or loses
#            points without any error signal)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 x qdrant_behavioral_points_query_003 — the contract
  states "offset pagination over HNSW is non-deterministic: the same point
  can repeat across pages; using exact=true gives stable ordering for
  offset pagination". On a 12-point seeded collection (dim 4, Euclid,
  ids 1..12), pages of limit=5 are walked via next_page_offset until the
  marker disappears (page-count guard: 8 pages max):
    X1  params={"exact": true} pagination walk -> union of all page ids
        EXACTLY == the 12 seeded ids (0 duplicates, 0 skips, 0 extras);
        per-page count min(5, remaining)
    X2  repeat of X1 -> IDENTICAL per-page id sequence (stability of the
        stable-ordering promise across repetitions)
    XH  exact omitted (plain HNSW) walk       -> 200 + structural sanity
        ONLY (arrays, len <= limit per page, walk terminates); duplicate
        or skipped ids across pages are EXEMPT here —
        SKIPPED: by-design per threat_model (issue #9523, maintainer-
        confirmed HNSW approximation limitation, not a defect)
  Rationale for the mutation point (G6): offset+limit pagination under
  exact=true is the seam where the deterministic promise lives; a page
  walk is the minimal complete witness of partition-ness that single-page
  probes cannot show.
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
  pagination stability x behavioral_points_query_003 (this script);
  strategy6 huge-offset resource x behavioral_points_query_002
  (offset_huge_001)]
Oracle: X1 -> every page 200; page id lists concatenate to exactly
  {1..12} with no duplicates and no skips (duplicate or missing id =
  Type4_StateLogicViolation: the exact=true stable-ordering promise is
  broken); X2 -> identical page-by-page id lists to X1 (divergence =
  Type4_StateLogicViolation: exact=true ordering is not stable);
  XH -> every page 200 with <= 5 points and a terminated walk (5xx with
  /healthz alive = Type3_RuntimeFailure; a non-terminating next_page_offset
  chain > 8 pages = Type4_StateLogicViolation on any leg; transport
  failure -> /healthz re-check then SCRIPT_ERROR) (constraint
  qdrant_behavioral_points_query_003).
Constraint: qdrant_behavioral_points_query_003 (bare id) — "by-design:
  without exact=true, points may repeat/skip across offset pages; with
  exact=true ordering is stable - page overlap under HNSW is not a defect"
  (evidence_tier: explicit; level: system)

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
PAGE = 5
MAX_PAGES = 8
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


def walk_pages(coll, label, use_exact):
    """Walk offset pages via next_page_offset; returns (page_id_lists, err_flag)."""
    body_req = {"query": {"nearest": V}, "limit": PAGE}
    if use_exact:
        body_req["params"] = {"exact": True}
    offset = None
    pages = []
    for page_i in range(MAX_PAGES):
        if offset is not None:
            body_req["offset"] = offset
        s, b, raw = safe_request("POST", f"/collections/{coll}/points/query",
                                 json=body_req, timeout=90)
        print(f"\n{label} page {page_i + 1} (offset={offset}) -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            alive, _, _ = healthz_alive()
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion" if alive else
                  "VERDICT: SCRIPT_ERROR — transport failure and healthz down")
            return None
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {label} page {page_i + 1}: "
                      f"returned {s} with service alive: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
            return None
        pts_a, shape = extract_points(b)
        if s != 200 or pts_a is None:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {label} page {page_i + 1}: "
                  f"valid pagination request rejected/malformed with {s} ({shape}): {raw[:300]}")
            return None
        if len(pts_a) > PAGE:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — {label} page "
                  f"{page_i + 1}: limit={PAGE} but {len(pts_a)} points returned: {raw[:300]}")
            return None
        pages.append([p.get("id") for p in pts_a])
        nxt = extract_next_offset(b)
        if nxt is None:
            return pages
        if not isinstance(nxt, int) or isinstance(nxt, bool):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — {label} page "
                  f"{page_i + 1}: next_page_offset is not an integer ({nxt!r}): {raw[:200]}")
            return None
        offset = nxt
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — {label}: next_page_offset "
          f"chain exceeded {MAX_PAGES} pages on a {N_SEED}-point collection (non-terminating "
          f"pagination)")
    return None


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpqX1" + tag

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

        seeded = set(range(1, N_SEED + 1))

        # ---- X1: exact=true walk must partition the id set ----
        pages1 = walk_pages(coll, "X1 exact=true", use_exact=True)
        if pages1 is None:
            return
        flat1 = [i for page in pages1 for i in page]
        dupes = sorted({i for i in flat1 if flat1.count(i) > 1})
        missing = sorted(seeded - set(flat1))
        extras = sorted(set(flat1) - seeded)
        print(f"\nX1 exact=true pages: {pages1}")
        if dupes or missing or extras:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — X1: exact=true "
                  f"pagination must give stable ordering (a partition of the stored ids), "
                  f"but observed duplicates={dupes} missing={missing} extras={extras} "
                  f"(constraint: with exact=true ordering is stable): see pages above")
            return
        if len(flat1) != N_SEED:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — X1: union size "
                  f"{len(flat1)} != {N_SEED} stored points although no id is duplicated: "
                  f"see pages above")
            return
        print("leg X1 OK: exact=true pages partition the 12 seeded ids exactly")

        # ---- X2: repeat walk -> identical page sequence ----
        pages2 = walk_pages(coll, "X2 exact=true repeat", use_exact=True)
        if pages2 is None:
            return
        print(f"\nX2 repeat pages: {pages2}")
        if pages2 != pages1:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — X2: exact=true "
                  f"ordering is NOT stable across repetitions: page sequence changed "
                  f"({pages1} -> {pages2}) (constraint: with exact=true ordering is stable)")
            return
        print("leg X2 OK: identical page sequence on repetition")

        # ---- XH: plain-HNSW walk — structural only (by-design exemption) ----
        pagesh = walk_pages(coll, "XH plain HNSW", use_exact=False)
        if pagesh is None:
            return
        flath = [i for page in pagesh for i in page]
        outside = sorted(set(flath) - seeded)
        if outside:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — XH: plain walk "
                  f"returned ids outside the seeded set {outside}: see pages above")
            return
        print("leg XH OK: structural checks pass (dupes/skips across pages EXEMPT — "
              "SKIPPED: by-design per threat_model, issue #9523 HNSW limitation)")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
