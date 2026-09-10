#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_recommend_offset_002
# strategy: strategy1 boundary-value attack on the offset parameter of the
#           recommend face (min-0 promise from the range constraint) plus a
#           conservative strategy6 huge-offset leg with result-count
#           arithmetic (max(0, candidates - offset)) as the oracle
# endpoint: points+recommend
# constraint_ids: qdrant_range_points_recommend_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/search/recommend-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — clients trust offset>=0 is
#            enforced and that offset slides the result window by
#            arithmetic; a server accepting offset=-1 or returning points
#            beyond the stored count silently corrupts pagination)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary x qdrant_range_points_recommend_001 — the
  contract asserts "offset minimum 0" on POST /collections/{c}/points/
  recommend. Boundary matrix on a 12-point seeded collection (dim 4,
  Euclid, binary-exact floats — R27), by-id positive example id=1
  (excluded from its own result set by the documented exclude-referenced-
  ids behavior, so 11 candidates remain), params.exact=true for
  deterministic ranking:
    O0     offset=0 (min legal closure)      -> 200, EXACTLY 2 points
    O1     offset=1 (min+1 closure)          -> 200, EXACTLY 2 points
                                               (window slides; NO
                                               cross-window duplicate
                                               claims — HNSW pagination
                                               duplicates are by-design
                                               per threat model #9523)
    Oneg   offset=-1 (below min)             -> 400/422 reject
    Otype  offset="1" (string; strategy2    -> 400/422 reject
           cross-leg)
    Ohuge  offset=1000000 limit=3            -> 200 with EXACTLY 0 points
           (conservative strategy6 leg; the             (arithmetic: 11
           OpenAPI itself warns "large offset values may               candidates <
           cause performance issues" — slow but                               offset) or a
           alive is acceptable; CRASH is the                            clean 400/422
           defect signal, R11 framing)
  [chunk_points+recommend coverage (11 scripts): strategy1 limit boundary
  matrix x qdrant_range_points_recommend_001 (limit_001); strategy1 offset
  boundary matrix + huge-offset x qdrant_range_points_recommend_001 (this
  script); behavioral positive core by-id/by-vector/strategy-enum closure
  x qdrant_behavioral_points_recommend_001 (positive_003); BS-10 missing
  referenced point ids 400-legs x qdrant_behavioral_points_recommend_001
  (missing_ref_004); using-vector characteristics mismatch (lookup dim +
  named partial) x qdrant_behavioral_points_recommend_001
  (using_mismatch_005); 404 status-mapping legs x
  qdrant_behavioral_points_recommend_001 (404_006); strategy2
  RecommendExample oneOf element type-confusion + raw-vector dimension x
  qdrant_behavioral_points_recommend_001 (example_type_007); R33/R40
  dual-key silent-drop family on mixed recommend examples x
  qdrant_behavioral_points_recommend_001 (dualkey_008); strategy2 filter
  type-confusion family mirror x qdrant_behavioral_points_recommend_001
  (filter_type_009); strategy6 conservative single-extreme +
  modest-product resource x qdrant_range_points_recommend_001
  (resource_010); strategy7 malformed raw-byte stream x
  qdrant_behavioral_points_recommend_001 (malformed_011)]
Oracle: O0/O1 -> 200 with EXACTLY 2 ScoredPoints each (11 candidates
  exist; wrong count or a non-array result envelope = Type4_StateLogic-
  Violation); Oneg/Otype -> 400 or 422 (200 = Type1_IllegalSuccess:
  negative / type-confused offset accepted; 404 = Type4 misattributed
  status); Ohuge -> 200 with EXACTLY 0 points or clean 400/422 (returning
  >0 points when offset exceeds the 11 candidates = Type4_StateLogic-
  Violation; 5xx/OOM with /healthz alive = Type3_RuntimeFailure; transport
  failure with /healthz alive = Type3 hang; transport death with /healthz
  DOWN after the huge-offset leg = Type3 server-killed-by-request, R11
  framing); transport failure on non-extreme legs -> /healthz liveness
  re-check then SCRIPT_ERROR (constraint qdrant_range_points_recommend_001).
Constraint: qdrant_range_points_recommend_001 (bare id) — "limit minimum 1
  (required); offset minimum 0" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+recommend      -> POST /collections/{collection_name}/points/recommend
  points+upsert         -> PUT  /collections/{collection_name}/points
  collections+create    -> PUT  /collections/{collection_name}
  collections+delete    -> DELETE /collections/{collection_name}
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
N_SEED = 12
V = [0.5, 0.25, 0.125, 0.0625]


def safe_request(method, endpoint, json=None, timeout=60, params=None):
    """Safe HTTP wrapper -> (status_code, body, raw_text); transport failure -> (-1, err, err)."""
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


def extract_scored(body):
    """Contract response_shape: result is a top-level array of ScoredPoints."""
    if not isinstance(body, dict):
        return None, "body-not-dict"
    result = body.get("result")
    if isinstance(result, list):
        return result, "result-array"
    return None, "result-missing-or-not-array"


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bprO2" + tag

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

        base = {"positive": [1], "params": {"exact": True}, "limit": 2}

        # ---- Legs O0 / O1: min closure and min+1 (both legal windows) ----
        for label, off in (("O0 offset=0", 0), ("O1 offset=1", 1)):
            s, b, raw = safe_request("POST", f"/collections/{coll}/points/recommend",
                                     json=dict(base, offset=off), timeout=60)
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
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: valid "
                          f"recommend returned {s} with service alive: {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return
            scored, shape = extract_scored(b)
            if s != 200 or scored is None:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{label}]: documented "
                      f"legal offset rejected/malformed with {s} ({shape}): {raw[:300]}")
                return
            if len(scored) != 2:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [{label}]: limit=2 "
                      f"with 11 candidates and offset={off} must return exactly 2 points, "
                      f"got {len(scored)}: {raw[:300]}")
                return
            print(f"leg {label} OK: exactly 2 ScoredPoints")

        # ---- Negative legs: Oneg / Otype -> must be rejected ----
        for label, off in (("Oneg offset=-1", -1), ("Otype offset='1'", "1")):
            s, b, raw = safe_request("POST", f"/collections/{coll}/points/recommend",
                                     json=dict(base, offset=off), timeout=60)
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
                          f"offset returned {s} (must be a clean 4xx) with service alive: {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return
            if s == 200:
                n = len(extract_scored(b)[0] or [])
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{label}]: contract "
                      f"asserts offset minimum 0, but the request was ACCEPTED with 200 "
                      f"({n} points returned): {raw[:300]}")
                return
            if s == 404:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [{label}]: 404 is "
                      f"the documented status for a MISSING COLLECTION; got 404 for an illegal "
                      f"offset: {raw[:300]}")
                return
            if s not in (400, 422):
                print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on leg [{label}]; no defect conclusion")
                return
            named = "offset" in raw.lower()
            print(f"leg {label} OK: rejected with {s} (error names 'offset': {named})")

        # ---- Leg Ohuge: offset=1000000 (conservative strategy6; R11 death-oracle) ----
        alive_before, hs_before, hraw_before = healthz_alive()
        if not alive_before:
            print(f"noise guard: /healthz down BEFORE any extreme leg ({hs_before}: {hraw_before})")
            print("VERDICT: SCRIPT_ERROR — environment not healthy before extreme leg")
            return
        s, b, raw = safe_request("POST", f"/collections/{coll}/points/recommend",
                                 json=dict(base, offset=1000000), timeout=120)
        print(f"\nleg Ohuge offset=1000000 -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1:
            alive, _, _ = healthz_alive()
            if alive:
                print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [Ohuge]: request did not "
                      "complete (transport error) while /healthz is alive (hang/DoS signal)")
            else:
                print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [Ohuge]: transport death "
                      "during an extreme leg with /healthz DOWN after it — server killed by the "
                      "request (resource_bound; R11 framing)")
            return
        if 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [Ohuge]: huge offset "
                      f"returned {s} with service alive (OOM/DoS): {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
            return
        if s in (200, 201):
            scored, shape = extract_scored(b)
            if scored is None:
                print(f"VERDICT: SCRIPT_ERROR — 200 but no result array on Ohuge ({shape}); no defect conclusion")
                return
            if len(scored) != 0:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [Ohuge]: offset "
                      f"1000000 exceeds the 11 available candidates, so EXACTLY 0 points may be "
                      f"returned, got {len(scored)}: {raw[:300]}")
                return
            print("leg Ohuge OK: 200 with exactly 0 points (offset arithmetic honored, no crash)")
        elif s in (400, 422):
            print(f"leg Ohuge OK: clean {s} rejection (resource-class norm)")
        else:
            print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on Ohuge; no defect conclusion")
            return

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
