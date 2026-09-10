#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_query_groups_dualkey_001
# strategy: strategy4 type-coercion attack (R33/R40 CONFIRMED serde-untagged
#           dual-key family extended to its THIRD face: the groups query
#           request's Query oneOf, cross-face G9 comparison against the
#           plain query face)
# endpoint: points+query+groups
# constraint_ids: qdrant_behavioral_points_query_groups_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points-groups
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — the reflection context
#            records the family CONFIRMED x2: serde untagged oneOf objects
#            silently drop the second variant key, 200 accepted, first
#            variant wins, proven on the upsert/points-get/query wrappers
#            (R33) and re-confirmed on the single+batch query faces (R40).
#            The GROUPS face's disposition for the same dual-key query
#            object is UNMEASURED; R27-calibrated read-face tolerance makes
#            consistent-accept benign, but a face DIVERGENCE (groups face
#            rejects while query face accepts, or a different variant wins)
#            silently changes what a ported query means)
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy4 type_coercion (dual-key family, novel_candidate third
  face) x qdrant_behavioral_points_query_groups_001 — QueryRequestQuery is
  oneOf {NearestQuery, RecommendQuery, ...} (vendored OpenAPI), so a query
  object carrying TWO variant keys is oneOf-ambiguous. Fixture: two groups
  GA (near the anchor vector) and GB (far from it, near the recommend
  seed), so pure-nearest and pure-recommend order the groups OPPOSITELY.
  All interpretation is read off LIVE baselines measured in the same run:
    GN groups face, pure {"nearest": ANCHOR}        -> fingerprint
    GR groups face, pure {"recommend": positive[GB seed id]} -> fingerprint
       (require GN != GR; the recommend face excludes the positive point
       itself by design — absorbed by the live baseline, never assumed)
    D  groups face, dual-key {"nearest": ANCHOR, "recommend": {...}} ->
       4xx (reject) or 200 matching GN / GR / other
    QN/QR/Q plain query face (points/query) same three probes ->
       disposition + winning variant (R40 measured this face; re-measured
       live for the same-run comparison)
  Adjudication (G9 — same payload, same query engine, two documented
  faces): both reject -> NO_DEFECT; both accept with the SAME winning
  variant -> NO_DEFECT + NOTE (family tolerance consistent on read faces
  per the R35/R40 calibration); divergence (one rejects / different
  variants win) -> DEFECT_FOUND (Type4).
  # exploration_target: novel_candidate (R33/R40 family's unmeasured face)
  [chunk_points+query+groups semantic coverage (9 scripts): illegal_rejection
  min-1 closure + 0/-1 rejection x qdrant_range_points_query_groups_001
  (bounds_001); type_coercion string/float/bool group_size+limit x
  qdrant_range_points_query_groups_001 (typecoerce_001); search_correctness
  group_size/limit semantics + defaults x qdrant_range_points_query_groups_001
  (semantics_001); metamorphic offset invariance x
  qdrant_state_points_query_groups_001 (offset_001); metamorphic offset
  disposition cross-face G9 x qdrant_state_points_query_groups_001
  (offset_faces_001); behavioral_contract 200-shape/invalid-group_by-400/404
  x qdrant_behavioral_points_query_groups_001 (behavior_001);
  diagnosis_quality 400/404 message rubric x
  qdrant_behavioral_points_query_groups_001 (diag_001); filter_semantics
  exact-set closure + must_not + range x
  qdrant_behavioral_points_query_groups_001 (filter_001); type_coercion
  R33/R40 dual-key family third face x
  qdrant_behavioral_points_query_groups_001 (dualkey_001)]
Oracle: GN and GR -> both 200 with DISTINCT group-order fingerprints (else
  SCRIPT_ERROR — interpretation undecidable); D and Q -> each 4xx or 200
  with fingerprint equal to exactly one live baseline (winner read off
  live, never assumed); NO_DEFECT iff D and Q land on the same disposition
  and, when both accepted, the same winning variant; DEFECT_FOUND
  (Type4_StateLogicViolation) iff the two faces' dispositions diverge or
  different variants win for the same payload (G9 cross-face asymmetry —
  a query ported between the documented faces silently changes meaning);
  5xx with /healthz alive = Type3_RuntimeFailure; transport failure ->
  /healthz liveness re-check then SCRIPT_ERROR (constraint
  qdrant_behavioral_points_query_groups_001).
Constraint: qdrant_behavioral_points_query_groups_001 — "grouping requires
  payload values for the group_by field; returns 200 {groups: [{id,
  hits}]}; 400 on an invalid group_by; 404 for a missing collection"
  (evidence_tier: explicit; level: endpoint); Query oneOf per the vendored
  OpenAPI (query.nearest / query.recommend variant keys in
  request_required_paths)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+query+groups -> POST /collections/{collection_name}/points/query/groups
  points+query        -> POST /collections/{collection_name}/points/query
  points+upsert       -> PUT  /collections/{collection_name}/points
  collections+create  -> PUT  /collections/{collection_name}
  collections+delete  -> DELETE /collections/{collection_name}
  field index create  -> PUT  /collections/{collection_name}/index
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
BASE3 = [10.0, 10.0, 10.0]
ANCHOR = [0.0, 10.0, 10.0, 10.0]   # nearest anchor: GA (d=1) beats GB (d=5)

# GA points sit at d=1/1.1 from ANCHOR; GB points at d=5/5.1 (and the
# recommend seed is GB's own point 2201, so pure-recommend flips the order)
SEED = [
    {"id": 2101, "vector": [1.0] + BASE3, "payload": {"grp": "GA"}},
    {"id": 2102, "vector": [1.1] + BASE3, "payload": {"grp": "GA"}},
    {"id": 2201, "vector": [5.0] + BASE3, "payload": {"grp": "GB"}},
    {"id": 2202, "vector": [5.1] + BASE3, "payload": {"grp": "GB"}},
]
RECO_SEED = 2201  # GB's best point


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


def bail_transport(where):
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


def groups_of(body):
    if isinstance(body, dict):
        r = body.get("result")
        if isinstance(r, dict) and isinstance(r.get("groups"), list):
            return r["groups"]
    return None


def gfp(groups):
    return [g.get("id") for g in groups or [] if isinstance(g, dict)]


def points_of(body):
    if isinstance(body, dict):
        r = body.get("result")
        if isinstance(r, dict) and isinstance(r.get("points"), list):
            return r["points"]
        if isinstance(r, list):
            return r
    return None


def ids_of(points):
    return [p.get("id") for p in points or [] if isinstance(p, dict)]


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "spqgK1" + tag
    gpath = f"/collections/{coll}/points/query/groups"
    qpath = f"/collections/{coll}/points/query"

    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": SEED}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return
        s, _, raw = safe_request("PUT", f"/collections/{coll}/index",
                                 json={"field_name": "grp", "field_schema": "keyword"},
                                 params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"NOTE setup: grp index create returned {s}: {raw[:200]}")

        dual = {"nearest": list(ANCHOR), "recommend": {"positive": [RECO_SEED]}}

        # ---- GN: groups face, pure nearest ----
        s, body, raw = safe_request("POST", gpath,
                                    json={"query": {"nearest": ANCHOR}, "group_by": "grp",
                                          "params": {"exact": True}, "group_size": 1,
                                          "limit": 2}, timeout=60)
        print(f"GN groups pure nearest -> status={s} raw: {raw[:350]}")
        if s == -1:
            bail_transport("GN")
            return
        if handle_5xx(s, raw, "GN"):
            return
        if not (200 <= s <= 299):
            print(f"VERDICT: SCRIPT_ERROR — GN unexpected status {s}; no defect conclusion")
            return
        gn = gfp(groups_of(body))

        # ---- GR: groups face, pure recommend ----
        s, body, raw = safe_request("POST", gpath,
                                    json={"query": {"recommend": {"positive": [RECO_SEED]}},
                                          "group_by": "grp", "params": {"exact": True},
                                          "group_size": 1, "limit": 2}, timeout=60)
        print(f"GR groups pure recommend -> status={s} raw: {raw[:350]}")
        if s == -1:
            bail_transport("GR")
            return
        if handle_5xx(s, raw, "GR"):
            return
        if not (200 <= s <= 299):
            print(f"NOTE GR: pure recommend control not accepted ({s}); the "
                  f"groups-face winner will be read against GN alone "
                  f"(reduced-decidability mode)")
            gr = None
        else:
            gr = gfp(groups_of(body))
        print(f"GN={gn} GR={gr}")
        if gn is None or len(gn) != 2 or (gr is not None and (len(gr) != 2 or gr == gn)):
            print("VERDICT: SCRIPT_ERROR — baselines unusable/colliding, "
                  "interpretation undecidable; no defect conclusion")
            return

        # ---- D: groups face, dual-key query ----
        s, body, raw = safe_request("POST", gpath,
                                    json={"query": dual, "group_by": "grp",
                                          "params": {"exact": True}, "group_size": 1,
                                          "limit": 2}, timeout=60)
        print(f"D groups dual-key -> status={s} raw: {raw[:400]}")
        if s == -1:
            bail_transport("D")
            return
        if handle_5xx(s, raw, "D"):
            return
        if 400 <= s <= 499:
            d_disp = ("reject", None)
        elif 200 <= s <= 299:
            got = gfp(groups_of(body))
            d_disp = ("accept", "nearest" if got == gn else
                      ("recommend" if got == gr else "other"))
            print(f"D fingerprint {got} -> disposition {d_disp}")
        else:
            print(f"VERDICT: SCRIPT_ERROR — D unexpected status {s}")
            return

        # ---- QN/QR/Q: plain query face, same three probes ----
        qn = qr = None
        s, body, raw = safe_request("POST", qpath,
                                    json={"query": {"nearest": ANCHOR},
                                          "params": {"exact": True}, "limit": 2}, timeout=60)
        if s == -1:
            bail_transport("QN")
            return
        if handle_5xx(s, raw, "QN"):
            return
        if 200 <= s <= 299:
            qn = ids_of(points_of(body))
        s, body, raw = safe_request("POST", qpath,
                                    json={"query": {"recommend": {"positive": [RECO_SEED]}},
                                          "params": {"exact": True}, "limit": 2}, timeout=60)
        if s == -1:
            bail_transport("QR")
            return
        if handle_5xx(s, raw, "QR"):
            return
        if 200 <= s <= 299:
            qr = ids_of(points_of(body))
        print(f"QN={qn} QR={qr}")
        if qn is None or qr is None or qn == qr:
            print("VERDICT: SCRIPT_ERROR — plain-face baselines unusable; no defect conclusion")
            return

        s, body, raw = safe_request("POST", qpath,
                                    json={"query": dual, "params": {"exact": True},
                                          "limit": 2}, timeout=60)
        print(f"Q plain-face dual-key -> status={s} raw: {raw[:400]}")
        if s == -1:
            bail_transport("Q")
            return
        if handle_5xx(s, raw, "Q"):
            return
        if 400 <= s <= 499:
            q_disp = ("reject", None)
        elif 200 <= s <= 299:
            got = ids_of(points_of(body))
            q_disp = ("accept", "nearest" if got == qn else
                      ("recommend" if got == qr else "other"))
            print(f"Q fingerprint {got} -> disposition {q_disp}")
        else:
            print(f"VERDICT: SCRIPT_ERROR — Q unexpected status {s}")
            return

        # ---- G9 cross-face adjudication ----
        print(f"groups face {d_disp} vs plain query face {q_disp}")
        if d_disp[0] == "reject" and q_disp[0] == "reject":
            print("both faces reject the oneOf-ambiguous dual-key payload — consistent enforcement")
            print("VERDICT: NO_DEFECT")
            return
        if d_disp[0] == "accept" and q_disp[0] == "accept":
            if d_disp[1] == q_disp[1]:
                print(f"NOTE both faces accept and the same variant wins "
                      f"({d_disp[1]}) — R33/R40 serde-untagged family tolerance "
                      f"holds CONSISTENTLY on this third (groups) face; second "
                      f"key silently discarded; read-face benign per the R35/R40 "
                      f"calibration; recorded for the judge")
                print("VERDICT: NO_DEFECT")
            else:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — the "
                      f"SAME dual-key query payload executes with DIFFERENT "
                      f"variants on the two faces: groups face -> {d_disp[1]}, "
                      f"plain query face -> {q_disp[1]}; porting a working query "
                      f"into (or out of) grouped form silently changes its "
                      f"meaning (G9 cross-face inconsistent disposition)")
            return
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — cross-face "
              f"inconsistent disposition of the same dual-key payload: groups "
              f"face {d_disp}, plain query face {q_disp} (G9 asymmetry; "
              f"R33/R40 family)")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
