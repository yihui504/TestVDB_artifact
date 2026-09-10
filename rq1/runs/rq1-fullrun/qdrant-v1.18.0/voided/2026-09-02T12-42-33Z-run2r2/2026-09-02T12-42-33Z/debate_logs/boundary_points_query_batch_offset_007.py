#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_query_batch_offset_007
# strategy: strategy1 boundary-value attack on searches[].offset — the
#           min-0 promise (qdrant_range_points_query_001) plus offset
#           pagination arithmetic on the batch face, measured against a
#           LIVE single-face baseline (R27 lesson: never compare against
#           assumed/uploaded values) with exact=true for deterministic
#           ordering (qdrant_behavioral_points_query_003)
# endpoint: points+query+batch
# constraint_ids: qdrant_behavioral_points_query_batch_001, qdrant_range_points_query_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/batch-query
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — offset arithmetic inside
#            batch entries could be applied globally instead of per-entry,
#            skipped, or left unvalidated against the min-0 promise)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 per-entry offset boundary x
  qdrant_behavioral_points_query_batch_001, oracle ground
  qdrant_range_points_query_001 ("offset minimum 0 (default 0)") and
  qdrant_behavioral_points_query_003 (exact=true gives stable ordering —
  used ONLY as a determinism device, no score oracle invented):
    BASE live-measured single-face ordering: nearest(blue-vec), exact=true,
       limit=9, offset=0 -> ordered id list L (9 ids, deterministic)
    O1 batch entry offset=3 limit=3 exact=true  -> ids == L[3:6] (page-2
       arithmetic, per-entry offset honored) AND identical to the single
       face sent the same body (G9 parity)
    Oneg batch entry offset=-1 (min-1 boundary) -> 400/422 on both faces
    Ohuge batch entry offset=999999999 limit=3  -> no 5xx/no crash (huge
       offsets are documented LEGAL: qdrant_behavioral_points_query_002 —
       200-with-empty-points preferred; 4xx recorded for the judge)
  [chunk_points+query+batch coverage: strategy1 positive order/count core x
  behavioral_points_query_batch_001 (positive_001); assertion 404 leg x
  behavioral_points_query_batch_001 (404_002); strategy2 searches wrapper
  type x behavioral_points_query_batch_001 (searches_type_003); strategy2
  entry presence matrix x behavioral_points_query_batch_001 (presence_004);
  R33-family dual-key enum discard x behavioral_points_query_batch_001
  (dualkey_005); strategy1 per-entry limit x behavioral_points_query_batch_001
  + range_points_query_001 min-1 ground (limit_006); strategy1 per-entry
  offset x behavioral_points_query_batch_001 + range_points_query_001 min-0
  ground (this script); mixed-variant universal-queries promise x
  behavioral_points_query_batch_001 (mixed_008); strategy6 batch-size
  resource x behavioral_points_query_batch_001 (resource_009); strategy7
  malformed stream x behavioral_points_query_batch_001 (malformed_010)]
Oracle: O1 -> 200 with result[0].points ids == L[3:6] (the LIVE baseline's
  page 2; mismatch = Type4_StateLogicViolation: per-entry offset arithmetic
  broken) and == the single-face ids for the same body (mismatch = G9
  asymmetry defect signal); Oneg -> 400/422 on both faces (2xx = Type1
  _IllegalSuccess: offset min-0 promise violated); Ohuge -> 200 with 0
  points (preferred, offsets legal) or 4xx (recorded for the judge); 5xx
  with /healthz alive = Type3_RuntimeFailure; transport failure ->
  /healthz liveness re-check then SCRIPT_ERROR (constraint
  qdrant_behavioral_points_query_batch_001).
Constraint: qdrant_behavioral_points_query_batch_001 (bare id) — "executes
  multiple queries in one call; returns 200 with a list of per-query results;
  404 for a missing collection" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+query+batch    -> POST /collections/{collection_name}/points/query/batch
  points+query          -> POST /collections/{collection_name}/points/query
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
BLUE_VEC = [0.0, 1.0, 0.0, 0.0]


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


def ids_of_points(points):
    out = []
    for p in points:
        if not isinstance(p, dict) or "id" not in p:
            return None
        out.append(p.get("id"))
    return out


def batch_entry_ids(body):
    """ids of result[0].points for a single-entry batch; None on mismatch."""
    if not isinstance(body, dict):
        return None
    res = body.get("result")
    if not isinstance(res, list) or len(res) != 1:
        return None
    elem = res[0]
    if not isinstance(elem, dict) or not isinstance(elem.get("points"), list):
        return None
    return ids_of_points(elem["points"])


def single_ids(body):
    if not isinstance(body, dict):
        return None
    res = body.get("result")
    if not isinstance(res, dict) or not isinstance(res.get("points"), list):
        return None
    return ids_of_points(res["points"])


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpqb7" + tag

    ok, raw = setup(coll)
    if not ok:
        print(f"setup failed: {str(raw)[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        # --- BASE: live single-face deterministic ordering (exact=true) ---
        base_entry = {"query": {"nearest": list(BLUE_VEC)},
                      "limit": N_SEED, "offset": 0, "params": {"exact": True}}
        sg, bg, rg = safe_request(
            "POST", f"/collections/{coll}/points/query",
            json=base_entry, timeout=60)
        print(f"BASE single-face ordering -> status={sg}")
        print(f"raw: {rg[:300]}")
        if sg == -1:
            alive, hs, hraw = healthz_alive()
            print(f"transport failure on BASE (healthz status={hs}: {hraw})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if not (200 <= sg <= 299):
            print(f"VERDICT: SCRIPT_ERROR — baseline leg returned {sg} "
                  f"(exact=true ordering unavailable; no oracle, no "
                  f"adjudication): {rg[:200]}")
            return
        L = single_ids(bg)
        if L is None or len(L) != N_SEED:
            print(f"VERDICT: SCRIPT_ERROR — baseline returned {L}; expected "
                  f"{N_SEED} ids for a full exact ordering")
            return
        print(f"BASE live-measured ordering L = {L}")

        # --- O1: batch entry offset=3 limit=3 (page-2 arithmetic + parity) ---
        o1 = {"query": {"nearest": list(BLUE_VEC)}, "limit": 3, "offset": 3,
              "params": {"exact": True}}
        sb, bb, rb = safe_request(
            "POST", f"/collections/{coll}/points/query/batch",
            json={"searches": [o1]}, timeout=60)
        sg1, bg1, rg1 = safe_request(
            "POST", f"/collections/{coll}/points/query", json=o1, timeout=60)
        print(f"\nO1 batch offset=3 -> status={sb}; single parity -> {sg1}")
        print(f"batch raw: {rb[:300]}")
        print(f"single raw: {rg1[:300]}")
        if sb == -1 or sg1 == -1:
            alive, hs, hraw = healthz_alive()
            print(f"transport failure on O1 (healthz status={hs}: {hraw})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        for st_, rw_, face in ((sb, rb, "batch"), (sg1, rg1, "single")):
            if 500 <= st_ <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — "
                          f"O1 on {face} face: returned {st_}: {rw_[:300]}")
                else:
                    print(f"VERDICT: SCRIPT_ERROR — O1 5xx and healthz down")
                return
        expected_page = L[3:6]
        got_b = batch_entry_ids(bb) if 200 <= sb <= 299 else None
        got_g = single_ids(bg1) if 200 <= sg1 <= 299 else None
        if not (200 <= sb <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — O1: valid "
                  f"documented batch entry rejected with {sb} (promise: "
                  f"HTTP 200): {rb[:300]}")
            return
        if got_b is None:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — O1: "
                  f"200 but result not one element carrying a points array: "
                  f"{rb[:300]}")
            return
        if got_b != expected_page:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — O1: "
                  f"per-entry offset arithmetic broken: expected page "
                  f"L[3:6]={expected_page}, got {got_b}: {rb[:300]}")
            return
        if got_g != expected_page:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — O1 "
                  f"G9: single face returned {got_g}, expected "
                  f"{expected_page}: {rg1[:300]}")
            return
        print(f"O1 upheld: batch page-2 {got_b} == single {got_g} == "
              f"L[3:6]")

        # --- Oneg: offset=-1 on both faces ---
        oneg = {"query": {"nearest": list(BLUE_VEC)}, "limit": 3, "offset": -1}
        sb2, _, rb2 = safe_request(
            "POST", f"/collections/{coll}/points/query/batch",
            json={"searches": [dict(oneg)]}, timeout=60)
        sg2, _, rg2 = safe_request(
            "POST", f"/collections/{coll}/points/query",
            json=dict(oneg), timeout=60)
        print(f"\nOneg offset=-1 -> batch status={sb2}, single status={sg2}")
        print(f"batch raw: {rb2[:300]}")
        print(f"single raw: {rg2[:300]}")
        if sb2 == -1 or sg2 == -1:
            alive, hs, hraw = healthz_alive()
            print(f"transport failure on Oneg (healthz status={hs}: {hraw})")
            print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        for st_, rw_, face in ((sb2, rb2, "batch"), (sg2, rg2, "single")):
            if 500 <= st_ <= 599:
                alive, _, _ = healthz_alive()
                if alive:
                    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — "
                          f"Oneg on {face} face: returned {st_}: {rw_[:300]}")
                else:
                    print("VERDICT: SCRIPT_ERROR — Oneg 5xx and healthz down")
                return
        acc_b2 = 200 <= sb2 <= 299
        acc_g2 = 200 <= sg2 <= 299
        if acc_b2:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — Oneg: "
                  f"offset=-1 ACCEPTED on the batch face with {sb2} "
                  f"(offset min-0 promise, qdrant_range_points_query_001): "
                  f"{rb2[:300]}")
            return
        if acc_g2:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — Oneg: "
                  f"offset=-1 ACCEPTED on the single face with {sg2}: "
                  f"{rg2[:300]}")
            return
        if (sb2 in (400, 422)) != (sg2 in (400, 422)):
            print(f"NOTE (G9): Oneg disposition asymmetry — batch {sb2} vs "
                  f"single {sg2}; recorded for the judge")
        else:
            print(f"Oneg: clean rejection on both faces (batch={sb2}, "
                  f"single={sg2})")

        # --- Ohuge: offset=999999999 (documented-legal huge offset) ---
        ohuge = {"query": {"nearest": list(BLUE_VEC)}, "limit": 3,
                 "offset": 999999999}
        sb3, bb3, rb3 = safe_request(
            "POST", f"/collections/{coll}/points/query/batch",
            json={"searches": [dict(ohuge)]}, timeout=90)
        print(f"\nOhuge offset=999999999 -> batch status={sb3}")
        print(f"raw: {rb3[:300]}")
        if sb3 == -1:
            alive, hs, hraw = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Ohuge: "
                      f"hang/transport failure on a documented-legal huge "
                      f"offset while /healthz alive")
            else:
                print("VERDICT: SCRIPT_ERROR — Ohuge transport failure and healthz down")
            return
        if 500 <= sb3 <= 599:
            alive, _, _ = healthz_alive()
            if alive:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Ohuge: "
                      f"returned {sb3} (huge offsets are documented legal): "
                      f"{rb3[:300]}")
            else:
                print("VERDICT: SCRIPT_ERROR — Ohuge 5xx and healthz down")
            return
        if 200 <= sb3 <= 299:
            got3 = batch_entry_ids(bb3)
            if got3 is None:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — "
                      f"Ohuge: 200 but result not one element carrying a "
                      f"points array: {rb3[:300]}")
                return
            if got3 != []:
                print(f"NOTE (judge): Ohuge 200 with non-empty page {got3} "
                      f"(offset far beyond the {N_SEED}-point collection); "
                      f"recorded for the judge")
            else:
                print("Ohuge upheld: 200 with empty page (legal)")
        else:
            print(f"NOTE (judge): Ohuge returned {sb3}; huge offsets are "
                  f"documented legal (qdrant_behavioral_points_query_002) — "
                  f"rejection recorded for the judge")

        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
