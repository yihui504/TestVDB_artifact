#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_recommend_behavior_001
# strategy: strategy1 behavioral-contract attack (status-disposition faces)
# endpoint: points+recommend
# constraint_ids: qdrant_behavioral_points_recommend_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/search/recommend-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-10 (missing positive/negative point IDs) — the contract's
#            behavioral words fix the disposition, not the TMA's 404 guess
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy1 behavioral 3-face x qdrant_behavioral_points_recommend_001 —
  the contract asserts: valid recommend returns HTTP 200 with scored points;
  a positive/negative referencing a MISSING point (or a point without the
  used vector) yields 400; a missing collection yields 404. Faces:
    A  valid positive id on a seeded dim-4 Euclid collection
       -> 200, result is a non-empty array of ScoredPoint (id+score present)
    B1 positive references a nonexistent id 999999 -> 400-family (400/422);
       2xx = Type1_IllegalSuccess (contract defect_type_if_violated);
       404 = DISPOSITION_NOTE (TMA hints a 404-on-missing-id doc variant
       exists; versioned contract words say 400 — recorded, not a defect)
    B2 negative references a nonexistent id 999999 (positive valid)
       -> 400-family; same typing as B1 (same parameter family, G9)
    C  recommend on a never-created collection -> 404;
       2xx = Type1_IllegalSuccess
    D  named-vectors collection {img, txt}; point carries only img;
       using=txt positive=that point -> 400-family ("references a point
       without the used vector"); 2xx = Type1_IllegalSuccess
    D+ control: same point with using=img -> 200 (point HAS img; the G4
       positive pairing that keeps face D grounded)
  [chunk_points+recommend semantic coverage — 7 scripts: 001 behavioral
   3-face x qdrant_behavioral_points_recommend_001; 002 diagnosis-quality
   x behavioral_001 (R38-calibrated); 003 limit/offset bounds closure x
   qdrant_range_points_recommend_001; 004 limit/offset type-coercion x
   range_001; 005 ranking + negative-steering formula x behavioral_001;
   006 filter semantics x behavioral_001; 007 metamorphic by-id==by-vector
   + RecommendExample oneOf dual-key x behavioral_001; this script = 001]
Oracle: A/D+ -> HTTP 200 with result a non-empty JSON array whose items
  carry id and numeric score (response_shape result[]: object,
  result[].id: any, result[].score: number); B1/B2/D -> 400-family 4xx
  (400 or 422 both satisfy the assertion's loose "400" per R16); C -> 404;
  any 2xx on B1/B2/C/D = Type1_IllegalSuccess; 5xx with /healthz alive =
  Type3_RuntimeFailure; transport failure -> /healthz re-check then
  SCRIPT_ERROR (constraint qdrant_behavioral_points_recommend_001).
Constraint: qdrant_behavioral_points_recommend_001 — "returns 200
  [ScoredPoint]; 400 when a positive/negative references a point without
  the used vector or a missing point (fetched vectors must match the
  using-vector characteristics); 404 for a missing collection"
  (evidence_tier: explicit; level: endpoint; defect_type_if_violated:
  Type1_IllegalSuccess)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+recommend       -> POST /collections/{collection_name}/points/recommend
  points+upsert          -> PUT  /collections/{collection_name}/points
  collections+create     -> PUT  /collections/{collection_name}
  collections+delete     -> DELETE /collections/{collection_name}
  healthz                -> GET  /healthz
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

# Seed: positive anchor 601 at x=10, candidates strictly left (x<10) so the
# result order is stable for any average_vector reading; only status faces
# are judged here, ranking is script 005's job.
SEED_MAIN = [{"id": 601, "vector": [10.0, 0.0, 0.0, 0.0]}] + [
    {"id": pid, "vector": [x, 0.0, 0.0, 0.0]}
    for pid, x in ((602, 9.4), (603, 9.0), (604, 8.0), (605, 6.0), (606, 3.0))
]
MISSING_ID = 999999


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


def get_results(body):
    """points+recommend response_shape: result = array[ScoredPoint] (direct list)."""
    if isinstance(body, dict):
        r = body.get("result")
        if isinstance(r, list):
            return r
    return None


def judge_reject_400family(rs, rraw, leg, note_codes=("404",)):
    """400-family (400/422) = promise honored (R16); other 4xx = disposition note."""
    if 200 <= rs <= 299:
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — [{leg}]: the "
              f"contract promises a 400 rejection here, got success {rs}: {rraw[:300]}")
        return "defect"
    if rs in (400, 422):
        print(f"[{leg}] OK: rejected with {rs} (400-family, promise honored)")
        return "ok"
    if 400 <= rs <= 499:
        print(f"DISPOSITION_NOTE [{leg}]: status {rs} instead of the documented "
              f"400-family (recorded per G9; TMA documents a 404-on-missing-id "
              f"variant): {rraw[:200]}")
        return "note"
    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — [{leg}]: unexpected "
          f"status {rs}: {rraw[:300]}")
    return "defect"


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "srbh" + tag
    coll_nv = "srbn" + tag
    coll_missing = "sr_missing_" + tag

    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create main failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    s, _, raw = safe_request("PUT", f"/collections/{coll_nv}",
                             json={"vectors": {"img": {"size": 4, "distance": "Euclid"},
                                               "txt": {"size": 4, "distance": "Euclid"}}},
                             timeout=60)
    if s not in (200, 201):
        print(f"setup create named failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": SEED_MAIN}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert main failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return
        # 501 carries ONLY the img vector; 502 carries both (control universe)
        s, _, raw = safe_request("PUT", f"/collections/{coll_nv}/points",
                                 json={"points": [
                                     {"id": 501, "vector": {"img": [10.0, 0.0, 0.0, 0.0]}},
                                     {"id": 502, "vector": {"img": [9.0, 0.0, 0.0, 0.0],
                                                            "txt": [9.5, 0.0, 0.0, 0.0]}}]},
                                 params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert named failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return

        rpath = f"/collections/{coll}/points/recommend"

        # ---- Face A: valid recommend by id -> 200 + ScoredPoint array ----
        sA, bA, rawA = safe_request("POST", rpath,
                                    json={"positive": [601], "limit": 3,
                                          "params": {"exact": True}}, timeout=60)
        print(f"A valid positive=[601] -> status={sA}")
        print(f"raw: {rawA[:400]}")
        if sA == -1:
            transport_dead("A valid"); return
        if handle_5xx(sA, rawA, "A valid"):
            return
        resA = get_results(bA)
        if sA != 200 or not resA:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — A: documented "
                  f"valid recommend must return 200 with a non-empty result array, "
                  f"got status={sA}, results={resA}: {rawA[:250]}")
            return
        if any(not isinstance(p, dict) or "id" not in p or not isinstance(p.get("score"), (int, float))
               for p in resA):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — A: result "
                  f"items do not match response_shape result[] ScoredPoint "
                  f"(id/score): {rawA[:250]}")
            return
        print(f"A OK: 200 with {len(resA)} scored points, ids={[p.get('id') for p in resA]}")

        # ---- Face B1: positive references a missing point ----
        sB1, _, rawB1 = safe_request("POST", rpath,
                                     json={"positive": [MISSING_ID], "limit": 3}, timeout=60)
        print(f"B1 positive=[{MISSING_ID}] (missing) -> status={sB1}")
        print(f"raw: {rawB1[:300]}")
        if sB1 == -1:
            transport_dead("B1 positive missing"); return
        if handle_5xx(sB1, rawB1, "B1 positive missing"):
            return
        if judge_reject_400family(sB1, rawB1, "B1 positive missing") == "defect":
            return

        # ---- Face B2: negative references a missing point ----
        sB2, _, rawB2 = safe_request("POST", rpath,
                                     json={"positive": [601], "negative": [MISSING_ID],
                                           "limit": 3}, timeout=60)
        print(f"B2 negative=[{MISSING_ID}] (missing) -> status={sB2}")
        print(f"raw: {rawB2[:300]}")
        if sB2 == -1:
            transport_dead("B2 negative missing"); return
        if handle_5xx(sB2, rawB2, "B2 negative missing"):
            return
        if judge_reject_400family(sB2, rawB2, "B2 negative missing") == "defect":
            return
        if (sB1 in (400, 422)) != (sB2 in (400, 422)):
            print(f"DISPOSITION_NOTE: same reference-error family disposed "
                  f"differently (positive={sB1} vs negative={sB2}) — G9 signal, "
                  f"recorded")

        # ---- Face C: missing collection -> 404 ----
        sC, _, rawC = safe_request("POST", f"/collections/{coll_missing}/points/recommend",
                                   json={"positive": [1], "limit": 3}, timeout=60)
        print(f"C missing collection -> status={sC}")
        print(f"raw: {rawC[:300]}")
        if sC == -1:
            transport_dead("C missing collection"); return
        if handle_5xx(sC, rawC, "C missing collection"):
            return
        if 200 <= sC <= 299:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — C: recommend on "
                  f"a never-created collection must 404, got success {sC}: {rawC[:250]}")
            return
        if sC == 404:
            print("C OK: missing collection -> 404 as documented")
        else:
            print(f"DISPOSITION_NOTE C: status {sC} instead of documented 404 "
                  f"(clear-diagnostics rejection, recorded not judged): {rawC[:200]}")

        # ---- Face D: referenced point lacks the used vector ----
        rpath_nv = f"/collections/{coll_nv}/points/recommend"
        sD, _, rawD = safe_request("POST", rpath_nv,
                                   json={"positive": [501], "using": "txt", "limit": 3},
                                   timeout=60)
        print(f"D positive=[501] using=txt (point has no txt) -> status={sD}")
        print(f"raw: {rawD[:300]}")
        if sD == -1:
            transport_dead("D without used vector"); return
        if handle_5xx(sD, rawD, "D without used vector"):
            return
        if 200 <= sD <= 299:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — D: point 501 has "
                  f"no 'txt' vector; the contract promises 400 for a positive "
                  f"referencing a point without the used vector, got success "
                  f"{sD}: {rawD[:250]}")
            return
        if sD in (400, 422):
            print("D OK: point-without-used-vector rejected with 400-family")
        else:
            print(f"DISPOSITION_NOTE D: status {sD} instead of documented "
                  f"400-family: {rawD[:200]}")

        # ---- Face D+ control: same point, using=img -> 200 ----
        sDp, bDp, rawDp = safe_request("POST", rpath_nv,
                                       json={"positive": [501], "using": "img", "limit": 3},
                                       timeout=60)
        print(f"D+ positive=[501] using=img (point HAS img) -> status={sDp}")
        print(f"raw: {rawDp[:300]}")
        if sDp == -1:
            transport_dead("D+ control"); return
        if handle_5xx(sDp, rawDp, "D+ control"):
            return
        if sDp != 200 or get_results(bDp) is None:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) — D+: the same "
                  f"point with the vector it DOES have (using=img) must succeed; "
                  f"got {sDp}: {rawDp[:250]}")
            return
        print("D+ OK: control face 200 — the D rejection is attributable to the "
              "missing used vector alone")

        print("VERDICT: NO_DEFECT")
    finally:
        for c in (coll, coll_nv):
            try:
                safe_request("DELETE", f"/collections/{c}", timeout=60)
            except Exception:
                pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
