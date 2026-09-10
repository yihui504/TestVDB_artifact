#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_recommend_filter_type_009
# strategy: strategy2 filter type-confusion family mirror — the R34/R35
#           measured grammar (type-confused Filter clause lists) probed on
#           the recommend face, with a LIVE valid-filter guard and an
#           ignored-filter discriminator (G9 cross-face consistency frame:
#           count face rejected R34, delete face accepted DESTRUCTIVELY
#           R35, discover face measured read-only — recommend is another
#           read-only member of the same family)
# endpoint: points+recommend
# constraint_ids: qdrant_behavioral_points_recommend_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/search/recommend-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — the recommend request
#            wraps filter in oneOf {Filter, Any} per the vendored OpenAPI;
#            clients trust the Filter schema is enforced; a 200 from an
#            invalid filter either silently ignores it (unfiltered
#            results) or feeds arbitrary JSON downstream)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 filter-type x qdrant_behavioral_points_recommend_001 —
  the recommend request's filter parameter (contract parameter spec:
  Filter {should?, min_should?, must?, must_not?}) is attacked with the
  same five type-confused faces measured on the delete/count/discover
  family, on a live seeded collection (12 points, 3 red / 9 blue,
  dim 4, Euclid, binary-exact — R27), with_payload=true so results carry
  the discriminating payload:
    G    guard: VALID filter must[grp=red] + positive=[1], limit=9 ->
         200, 1..3 results, EVERY result payload grp=="red"
         (arithmetic-derived: the filter admits at most the 3 seeded red
         points — proves the filter path live and semantics-correct
         before any 400 is trusted, G4 pairing)
    T1   {"filter": {"must": "red"}}                    clause list as STRING
    T2   {"filter": {"must_not": {"key": "grp"}}}       clause list as OBJECT
    T3   {"filter": {"should": 42}}                     clause list as INT
    T4   {"filter": {"must": [{"key":"grp","match": null}]}}  match = null
    T5   {"filter": {"must": [{"match": {"value":"red"}}]}}   key missing
  Each invalid face: expected 400/422 clean rejection. A 2xx is Type1
  with a LIVE ignored-filter discriminator: if any returned point is NOT
  grp=red, the invalid filter was silently treated as absent (unfiltered
  recommend) — the read-only member of the R35 destructive family; the
  cross-face disposition (count R34 NOT / delete R35 DEFECT / discover
  read-only / recommend = this face) is recorded for the G9 judge.
  [chunk_points+recommend coverage (11 scripts): strategy1 limit boundary
  matrix x qdrant_range_points_recommend_001 (limit_001); strategy1 offset
  boundary matrix + huge-offset x qdrant_range_points_recommend_001
  (offset_002); behavioral positive core by-id/by-vector/strategy-enum
  closure x qdrant_behavioral_points_recommend_001 (positive_003); BS-10
  missing referenced point ids 400-legs x qdrant_behavioral_points_
  recommend_001 (missing_ref_004); using-vector characteristics mismatch
  (lookup dim + named partial) x qdrant_behavioral_points_recommend_001
  (using_mismatch_005); 404 status-mapping legs x qdrant_behavioral_
  points_recommend_001 (404_006); strategy2 RecommendExample oneOf element
  type-confusion + raw-vector dimension x qdrant_behavioral_points_
  recommend_001 (example_type_007); R33/R40 dual-key silent-drop family on
  mixed recommend examples x qdrant_behavioral_points_recommend_001
  (dualkey_008); strategy2 filter type-confusion family mirror x
  qdrant_behavioral_points_recommend_001 (this script); strategy6
  conservative single-extreme + modest-product resource x
  qdrant_range_points_recommend_001 (resource_010); strategy7 malformed
  raw-byte stream x qdrant_behavioral_points_recommend_001
  (malformed_011)]
Oracle: G -> 200 with 1..3 results, every result payload grp=="red"
  (other length = Type4; any non-red result = Type4_StateLogicViolation;
  non-200 = valid filtered recommend rejected, Type1 convention per
  session); T1..T5 -> 400/422 clean rejection (any 2xx =
  Type1_IllegalSuccess — invalid filter accepted; if the 2xx results
  contain a non-red point the filter was silently IGNORED, live proof;
  count before/after stays 12, read-only face by construction); 5xx with
  /healthz alive = Type3_RuntimeFailure; transport failure -> /healthz
  liveness re-check then SCRIPT_ERROR
  (constraint qdrant_behavioral_points_recommend_001).
Constraint: qdrant_behavioral_points_recommend_001 (bare id) — "returns
  200 [ScoredPoint]; 400 when a positive/negative references a point
  without the used vector or a missing point (fetched vectors must match
  the using-vector characteristics); 404 for a missing collection"
  (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+recommend      -> POST /collections/{collection_name}/points/recommend
  points+upsert         -> PUT  /collections/{collection_name}/points
  points+count          -> POST /collections/{collection_name}/points/count
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
V = [0.5, 0.25, 0.125, 0.0625]
N_RED = 3
N_BLUE = 9


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
    coll = "bprF9" + tag

    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        pts = []
        for i in range(1, N_RED + 1):
            pts.append({"id": i, "vector": [v * (1.0 + i / 100.0) for v in V],
                        "payload": {"grp": "red"}})
        for j in range(1, N_BLUE + 1):
            i = N_RED + j
            pts.append({"id": i, "vector": [-v * (1.0 + j / 100.0) for v in V],
                        "payload": {"grp": "blue"}})
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": pts}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return

        # ---- Leg G: valid filter guard (live, semantics-correct) ----
        s, b, raw = safe_request("POST", f"/collections/{coll}/points/recommend",
                                 json={"positive": [1], "limit": 9, "params": {"exact": True},
                                       "with_payload": True,
                                       "filter": {"must": [{"key": "grp",
                                                            "match": {"value": "red"}}]}},
                                 timeout=60)
        print(f"\nleg G valid filter must[grp=red] -> status={s}")
        print(f"raw: {raw[:400]}")
        if s == -1 or 500 <= s <= 599:
            alive, _, _ = healthz_alive()
            if s == -1:
                print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion" if alive
                      else "VERDICT: SCRIPT_ERROR — transport failure and healthz down")
            elif alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [G]: {s} with "
                      f"service alive: {raw[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
            return
        scored, shape = extract_scored(b)
        if s != 200 or scored is None:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [G]: valid filtered "
                  f"recommend rejected/malformed with {s} ({shape}): {raw[:300]}")
            return
        if not (1 <= len(scored) <= N_RED):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [G]: the filter "
                  f"admits at most {N_RED} seeded red points, got {len(scored)}: {raw[:300]}")
            return
        bad = [sp.get("id") for sp in scored
               if not (isinstance(sp.get("payload"), dict)
                       and sp["payload"].get("grp") == "red")]
        if bad:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — leg [G]: non-red "
                  f"results leaked through the valid filter, ids {bad}: {raw[:300]}")
            return
        print(f"leg G OK: {len(scored)} red-only results — filter path live and correct")

        # ---- Legs T1..T5: type-confused filter faces ----
        t_legs = (
            ("T1 must as STRING", {"must": "red"}),
            ("T2 must_not as OBJECT", {"must_not": {"key": "grp"}}),
            ("T3 should as INT", {"should": 42}),
            ("T4 match=null", {"must": [{"key": "grp", "match": None}]}),
            ("T5 key missing", {"must": [{"match": {"value": "red"}}]}),
        )
        for label, flt in t_legs:
            s, b, raw = safe_request("POST", f"/collections/{coll}/points/recommend",
                                     json={"positive": [1], "limit": 9,
                                           "params": {"exact": True},
                                           "with_payload": True, "filter": flt}, timeout=60)
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
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: "
                          f"type-confused filter produced {s} (must be a clean 4xx) with "
                          f"service alive: {raw[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
                return
            if 200 <= s <= 299:
                scored, shape = extract_scored(b)
                ids = [sp.get("id") for sp in (scored or [])]
                non_red = [sp.get("id") for sp in (scored or [])
                           if not (isinstance(sp.get("payload"), dict)
                                   and sp["payload"].get("grp") == "red")]
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [{label}]: invalid "
                      f"filter accepted with {s}; returned ids {ids[:9]}"
                      + (f"; NON-RED ids {non_red} prove the filter was silently IGNORED "
                         f"(treated as absent — unfiltered recommend; read-only member of the "
                         f"R35 destructive family)" if non_red else
                         " (no non-red point returned; acceptance itself is the violation)")
                      + f": {raw[:300]}")
                return
            if s not in (400, 422):
                print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on leg [{label}]; no defect conclusion")
                return
            named = "filter" in raw.lower() or "must" in raw.lower() or "should" in raw.lower()
            print(f"leg {label} OK: rejected with {s} (error names the filter family: {named})")

        # read-only certification for the G9 judge: count unchanged
        s, b, raw = safe_request("POST", f"/collections/{coll}/points/count",
                                 json={"exact": True}, timeout=60)
        if s == 200 and isinstance(b, dict):
            cnt = b.get("result", {}).get("count") if isinstance(b.get("result"), dict) else None
            print(f"\npost-certification: point count after all legs = {cnt} (seeded 12; "
                  f"read-only face by construction)")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
