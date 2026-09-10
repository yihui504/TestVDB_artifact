#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_query_exact_pagination_001
# strategy: strategy5 search-correctness attack (exact=true stable pagination
#           promise) — the by-design HNSW overlap face is explicitly skipped
# endpoint: points+query
# constraint_ids: qdrant_behavioral_points_query_003
# source_url: https://qdrant.tech/documentation/search/search/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-05 (search semantics) — SKIPPED: by-design per threat_model:
#            HNSW approximate offset pagination may repeat points across
#            pages (issue #9523, maintainer-confirmed). Only the exact=true
#            stability promise is attacked here.
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy5 exact-pagination stability x qdrant_behavioral_points_query_003 —
  the contract documents: WITHOUT exact=true, offset pagination over HNSW is
  non-deterministic and may repeat points across pages (SKIPPED: by-design
  per threat_model, issue #9523 — not judged). WITH exact=true the ordering
  is STABLE for offset pagination — that promise IS attacked. 25 collinear
  points with graded distinct distances (id 401+b at vector [b,0,0,0],
  query [0,0,0,0], Euclid -> distance = b, score = 1/(1+b)), so the exact
  ranking is fully derivable. Legs:
    C1 full exact search limit=25
       -> 25 points, ids 401..425 ascending, scores descending 1.0, 0.5,
          1/3, ... (search-correctness face of the same constraint)
    C2 paginate limit=10 at offsets 0/10/20 with exact=true
       -> page sizes 10/10/5; the concatenation of pages equals C1 EXACTLY
          (slice equality per page — the strong form of stable ordering:
          paginated exact order == full exact order, so no point is
          repeated or skipped across pages)
    C3 within-page score monotonicity (non-increasing scores)
  [chunk_points+query semantic coverage — see variant_domain_001 for the
  full 10-script coverage list; this script = exact-pagination x
  qdrant_behavioral_points_query_003]
Oracle: C1 -> HTTP 200, result.points has 25 entries with ids == [401..425]
  and scores strictly non-increasing starting at 1.0; C2 -> page k ids ==
  C1 ids[k*10:(k+1)*10] for k=0,1,2 (union = all 25, no duplicate, no gap);
  C3 -> scores non-increasing inside each page; any violation =
  Type4_StateLogicViolation (the exact=true stability promise is broken);
  4xx on any leg = Type1_IllegalSuccess; 5xx with /healthz alive =
  Type3_RuntimeFailure; transport failure -> /healthz re-check then
  SCRIPT_ERROR (constraint qdrant_behavioral_points_query_003).
Constraint: qdrant_behavioral_points_query_003 (bare id) — "by-design:
  without exact=true, points may repeat/skip across offset pages; with
  exact=true ordering is stable — page overlap under HNSW is not a defect"
  (evidence_tier: explicit; level: system)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+query        -> POST /collections/{collection_name}/points/query
  points+upsert       -> PUT  /collections/{collection_name}/points
  collections+create  -> PUT  /collections/{collection_name}
  collections+delete  -> DELETE /collections/{collection_name}
  healthz             -> GET  /healthz
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
N = 25
IDS = [401 + b for b in range(N)]          # id 401+b, distance b from query
QUERY_VEC = [0.0, 0.0, 0.0, 0.0]
SEED = [{"id": 401 + b, "vector": [float(b), 0.0, 0.0, 0.0]} for b in range(N)]


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
    hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
    return hs == 200, hs, str(hraw)[:200]


def transport_dead(where):
    alive, hs, hraw = healthz_alive()
    print(f"transport failure on {where} (healthz status={hs}: {hraw})")
    print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")


def handle_5xx(rs, rraw, leg):
    if not (500 <= rs <= 599):
        return False
    alive, _, _ = healthz_alive()
    if alive:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{leg}]: {rs} "
              f"with service alive: {rraw[:300]}")
    else:
        print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
    return True


def get_points(body):
    if isinstance(body, dict):
        r = body.get("result")
        if isinstance(r, dict) and isinstance(r.get("points"), list):
            return r["points"]
    return None


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "spqE1" + tag

    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        # upsert in REVERSE id order: ranking must come from geometry, not
        # insertion order
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": list(reversed(SEED))},
                                 params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return

        qpath = f"/collections/{coll}/points/query"

        def exact_query(leg, limit, offset):
            s, body, raw = safe_request("POST", qpath,
                                        json={"query": {"nearest": QUERY_VEC},
                                              "params": {"exact": True},
                                              "limit": limit, "offset": offset}, timeout=60)
            print(f"{leg} -> status={s}")
            print(f"raw: {raw[:300]}")
            if s == -1:
                transport_dead(leg)
                return None
            if handle_5xx(s, raw, leg):
                return None
            if 400 <= s <= 499:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {leg}: "
                      f"spec-legal exact search rejected with {s}: {raw[:250]}")
                return "DEFECT"
            pts = get_points(body)
            if s != 200 or pts is None:
                print(f"VERDICT: SCRIPT_ERROR — {leg} unexpected status {s}; no "
                      f"defect conclusion")
                return None
            return [(p.get("id"), float(p.get("score", 0.0))) for p in pts]

        # ---- C1: full exact search ----
        full = exact_query("C1 full exact limit=25", 25, 0)
        if full in (None, "DEFECT"):
            return
        if [pid for pid, _ in full] != IDS:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — C1: exact "
                  f"Euclid ranking of collinear graded points must be ids "
                  f"{IDS[:5]}...{IDS[-1]} ascending, got {[p for p, _ in full][:10]}...")
            return
        if abs(full[0][1] - 1.0) > 1e-6 or abs(full[1][1] - 0.5) > 1e-6:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — C1: scores "
                  f"must be 1/(1+distance): expected [1.0, 0.5, ...], got "
                  f"{[round(sc, 6) for _, sc in full[:3]]}")
            return
        for (i1, s1), (i2, s2) in zip(full, full[1:]):
            if s2 > s1 + 1e-9:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — C1: "
                      f"score increases down the ranking at id {i1}->{i2} "
                      f"({s1} -> {s2})")
                return
        print("C1 OK: exact ranking derivable, scores = 1/(1+d), monotone")

        # ---- C2: paginated exact search must slice-match the full order ----
        pages = []
        for k, off in enumerate((0, 10, 20)):
            page = exact_query(f"C2 page{k} offset={off} limit=10", 10, off)
            if page in (None, "DEFECT"):
                return
            pages.append(page)

        expected_sizes = [10, 10, 5]
        for k, (page, want) in enumerate(zip(pages, expected_sizes)):
            if len(page) != want:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — C2 "
                      f"page{k}: expected {want} points (25 total, offset {k*10}), "
                      f"got {len(page)}")
                return
        concatenated = [pid for page in pages for pid, _ in page]
        full_ids = [pid for pid, _ in full]
        if concatenated != full_ids:
            dupes = {x for x in concatenated if concatenated.count(x) > 1}
            missing = [x for x in full_ids if x not in concatenated]
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — C2: with "
                  f"exact=true the documented stable ordering requires paginated "
                  f"results to slice-match the full order; duplicates={sorted(dupes)} "
                  f"missing={missing}")
            return
        print("C2 OK: 3 pages slice-match the full exact order exactly "
              "(no repeats, no gaps)")

        # ---- C3: within-page score monotonicity ----
        for k, page in enumerate(pages):
            for (i1, s1), (i2, s2) in zip(page, page[1:]):
                if s2 > s1 + 1e-9:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — C3 "
                          f"page{k}: score increases down the page at {i1}->{i2}")
                    return
        print("C3 OK: scores non-increasing within every page")

        print("SKIPPED: by-design per threat_model — approximate (exact=false) "
              "HNSW offset-pagination overlap is a documented limitation "
              "(issue #9523), not attacked")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
