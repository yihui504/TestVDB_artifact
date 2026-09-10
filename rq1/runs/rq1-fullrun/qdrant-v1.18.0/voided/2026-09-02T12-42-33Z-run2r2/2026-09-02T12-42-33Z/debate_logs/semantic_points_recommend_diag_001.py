#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_recommend_diag_001
# strategy: strategy2 error-diagnostics quality (Type-2) on the documented
#           400 reference-error faces of points+recommend
# endpoint: points+recommend
# constraint_ids: qdrant_behavioral_points_recommend_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/search/recommend-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-02 (Error Message Negligence) + BS-10 (missing reference ids)
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy2 diagnosis-quality x qdrant_behavioral_points_recommend_001 —
  the contract promises 400 for the reference-error faces of recommend
  (missing referenced point; referenced point without the used vector).
  This script scores the REJECTION BODIES of those faces with the 3-point
  rubric (offender identified 1pt / format-range hint 1pt / actionable
  suggestion 1pt), R38-calibrated: R29 measured that qdrant error naming
  has NO contract anchor, so parameter NAMING is informational only and a
  Type2 defect is declared ONLY for a rejection body with no usable
  content at all (empty body, or a bare generic error that identifies no
  offender and hints nothing). Legs:
    L1 positive references missing id 977777   -> 400-family; body scored
    L2 negative references missing id 977777
       (positive valid)                        -> 400-family; body scored
    L3 named-vectors point without 'txt' referenced with using=txt
                                              -> 400-family; body scored
    L0 positive control (valid id)             -> 200 (setup sanity)
  [chunk_points+recommend semantic coverage — see
   semantic_points_recommend_behavior_001 docstring for the full 7-script
   list; this script = 002 diagnosis-quality x behavioral_001]
Oracle: L1/L2/L3 -> 400-family 4xx whose body contains at least one usable
  cue (the offending id 977777 or vector name 'txt' or a param name, OR a
  format/range word, OR an actionable verb); rubric score >= 1 = pass;
  score == 0 (empty body / bare internal-error with no cue) =
  Type2_PoorDiagnostics; any 2xx on L1/L2/L3 = Type1_IllegalSuccess
  (rejection promise itself violated — script 001's primary face);
  5xx with /healthz alive = Type3_RuntimeFailure; transport failure ->
  /healthz re-check then SCRIPT_ERROR (constraint
  qdrant_behavioral_points_recommend_001).
Constraint: qdrant_behavioral_points_recommend_001 — "400 when a
  positive/negative references a point without the used vector or a
  missing point" (evidence_tier: explicit; level: endpoint;
  defect_type_if_violated: Type1_IllegalSuccess)

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

SEED_MAIN = [{"id": 601, "vector": [10.0, 0.0, 0.0, 0.0]}] + [
    {"id": pid, "vector": [x, 0.0, 0.0, 0.0]}
    for pid, x in ((602, 9.4), (603, 9.0), (604, 8.0), (605, 6.0), (606, 3.0))
]
MISSING_ID = 977777

FORMAT_HINTS = ["must be", "expected", "should be", "valid", "range", "type",
                "positive", "non-zero", "minimum", "required", "at least"]
ACTION_HINTS = ["correct", "try", "use", "change", "specify", "provide", "check"]


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


def score_rejection(body, raw, offender_tokens, leg):
    """
    3-point rubric on the rejection body (R38-calibrated):
      c1 offender identified (offending id / vector name / param name)
      c2 format/range hint
      c3 actionable suggestion
    Hard Type2 oracle: total == 0 (no usable content at all).
    """
    text = json.dumps(body, ensure_ascii=False).lower() if isinstance(body, dict) \
        else str(body).lower()
    if not text.strip():
        text = raw.lower()
    c1 = any(str(t).lower() in text for t in offender_tokens)
    c2 = any(h in text for h in FORMAT_HINTS)
    c3 = any(h in text for h in ACTION_HINTS)
    score = int(c1) + int(c2) + int(c3)
    print(f"[{leg}] rubric: offender_identified={c1} format_hint={c2} "
          f"actionable={c3} -> score={score}/3")
    return score


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "srdg" + tag
    coll_nv = "srdn" + tag

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
        # 511 carries ONLY img; referenced with using=txt it is the L3 face
        s, _, raw = safe_request("PUT", f"/collections/{coll_nv}/points",
                                 json={"points": [
                                     {"id": 511, "vector": {"img": [10.0, 0.0, 0.0, 0.0]}},
                                     {"id": 512, "vector": {"img": [9.0, 0.0, 0.0, 0.0],
                                                            "txt": [9.5, 0.0, 0.0, 0.0]}}]},
                                 params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert named failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return

        rpath = f"/collections/{coll}/points/recommend"
        legs = []

        # ---- L0 sanity: valid recommend must be 200 (keeps the setup honest) ----
        s0, b0, raw0 = safe_request("POST", rpath,
                                    json={"positive": [601], "limit": 3}, timeout=60)
        print(f"L0 valid positive=[601] -> status={s0}")
        print(f"raw: {raw0[:200]}")
        if s0 == -1:
            transport_dead("L0"); return
        if handle_5xx(s0, raw0, "L0"):
            return
        if s0 != 200 or not (isinstance(b0, dict) and isinstance(b0.get("result"), list)):
            print(f"VERDICT: SCRIPT_ERROR — sanity face L0 not 200/result-array "
                  f"(status={s0}); diagnosis faces not measurable: {raw0[:200]}")
            return

        # ---- L1: missing positive id ----
        s1, b1, raw1 = safe_request("POST", rpath,
                                    json={"positive": [MISSING_ID], "limit": 3}, timeout=60)
        print(f"L1 positive=[{MISSING_ID}] -> status={s1}")
        print(f"raw: {raw1[:300]}")
        if s1 == -1:
            transport_dead("L1"); return
        if handle_5xx(s1, raw1, "L1"):
            return
        legs.append(("L1 positive-missing", s1, b1, raw1,
                     [MISSING_ID, "positive", "example"]))

        # ---- L2: missing negative id ----
        s2, b2, raw2 = safe_request("POST", rpath,
                                    json={"positive": [601], "negative": [MISSING_ID],
                                          "limit": 3}, timeout=60)
        print(f"L2 negative=[{MISSING_ID}] -> status={s2}")
        print(f"raw: {raw2[:300]}")
        if s2 == -1:
            transport_dead("L2"); return
        if handle_5xx(s2, raw2, "L2"):
            return
        legs.append(("L2 negative-missing", s2, b2, raw2,
                     [MISSING_ID, "negative", "example"]))

        # ---- L3: referenced point without the used vector ----
        s3, b3, raw3 = safe_request("POST", f"/collections/{coll_nv}/points/recommend",
                                    json={"positive": [511], "using": "txt", "limit": 3},
                                    timeout=60)
        print(f"L3 positive=[511] using=txt (no txt vector) -> status={s3}")
        print(f"raw: {raw3[:300]}")
        if s3 == -1:
            transport_dead("L3"); return
        if handle_5xx(s3, raw3, "L3"):
            return
        legs.append(("L3 without-used-vector", s3, b3, raw3,
                     ["511", "txt", "vector", "using"]))

        # ---- adjudication: status first, then rubric (R38-calibrated) ----
        for name, st, bdy, rw, tokens in legs:
            if 200 <= st <= 299:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {name}: "
                      f"contract promises a 400 rejection, got success {st}: "
                      f"{rw[:300]}")
                return
            if not (400 <= st <= 499):
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {name}: "
                      f"unexpected status {st}: {rw[:300]}")
                return
            score = score_rejection(bdy, rw, tokens, name)
            if score == 0:
                print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — {name}: "
                      f"rejection {st} body carries no usable diagnostic content "
                      f"(no offender, no format hint, no action): {rw[:300]}")
                return
            print(f"[{name}] OK: rejected {st} with usable diagnostics (score>=1)")

        print("VERDICT: NO_DEFECT")
    finally:
        for c in (coll, coll_nv):
            try:
                safe_request("DELETE", f"/collections/{c}", timeout=60)
            except Exception:
                pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
