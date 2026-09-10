#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_points_query_groups_dualkey_001
# strategy: strategy2 oneOf dual-key attack — the R33/R40 serde-untagged
#           dual-key family ({"nearest": ..., "recommend": ...} in one
#           query object) measured on the groups face vs the single query
#           face; G9 cross-face consistency adjudication with LIVE
#           baselines (no assumed winner — R39 lesson)
# endpoint: points+query+groups
# constraint_ids: qdrant_behavioral_points_query_groups_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points-groups
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — QueryRequestQuery
#            resolves to a oneOf; a client sending two variant keys in one
#            object has an ambiguous intent, and R33/R40 PROVED serde
#            untagged resolution silently discards the second key on
#            upsert/points-get/query wrappers; this script asks whether the
#            groups face disposes of the SAME ambiguity consistently with
#            the single query face)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 dual-key oneOf x qdrant_behavioral_points_query_groups_001
  — the vendored OpenAPI types Query = oneOf {NearestQuery,
  RecommendQuery, ...}, so a query object carrying TWO variant keys
  ({"nearest": [V], "recommend": {"positive": [5]}}) is oneOf-ambiguous:
  not licensed by the schema. R33/R40 proved serde untagged dual-key
  objects silently discard the second key (upsert/points-get/query faces);
  the R35 read-face calibration treats CONSISTENT tolerance on read faces
  as benign and cross-face INCONSISTENCY as the defect. This script
  measures both faces with LIVE baselines (winner read off by fingerprint
  comparison against pure-nearest and pure-recommend runs in the same
  execution — never assumed):
    seed   cluster A ids 1-3 (grp=a, vectors near +V), cluster B ids 4-6
           (grp=b, vectors near -V); params.exact=true throughout
    SN  single face (POST points/query) pure nearest        -> fp FN
    SR  single face pure recommend positive=[5]             -> fp FR
    GFN groups  face pure nearest                           -> grouped fp GFN
    GFR groups  face pure recommend                         -> grouped fp GFR
    SD  single face DUAL-KEY query object                   -> 4xx, or 200
        with fp == FN or FR (winner recorded)
    GD  groups  face DUAL-KEY query object                  -> 4xx, or 200
        with grouped fp == GFN or GFR (winner recorded)
  Adjudication (G9 — the SAME ambiguous payload on the two faces of the
  same query engine must get a consistent disposition):
    - both faces 4xx                     -> NO_DEFECT (oneOf enforced)
    - both faces 2xx, same winner (or winner undetectable but both 2xx)
                                         -> NO_DEFECT (consistent untagged
      tolerance, R33-family shape; winner recorded)
    - one face 2xx while the other 4xx, or both 2xx with DIFFERENT winners
      -> DEFECT_FOUND (Type4_StateLogicViolation): cross-face inconsistent
      disposition — a client porting a working single query into a grouped
      query silently gets different semantics
  [chunk_points+query+groups coverage (8 scripts): strategy1 group_size
  boundary x range_points_query_groups_001 (groupsize_001); strategy1 limit
  boundary x range_points_query_groups_001 (limit_001); strategy6 limit x
  group_size resource combo x range_points_query_groups_001 (resource_001);
  state offset-not-allowed reject-or-omit x state_points_query_groups_001
  (offset_001); behavioral positive grouping-correctness + keyless-point
  exclusion x behavioral_points_query_groups_001 (groupby_values_001);
  strategy2 invalid group_by faces + 404 x behavioral_points_query_groups_001
  (invalid_groupby_001); strategy2 R33/R40 dual-key oneOf cross-face
  (single vs groups) x behavioral_points_query_groups_001 (this script);
  strategy7 malformed stream x behavioral_points_query_groups_001
  (malformed_001)]
Oracle: SN/SR -> 200 each with FN != FR (discrimination precondition; equal
  fingerprints or a 4xx baseline = SCRIPT_ERROR, no defect conclusion);
  GFN/GFR -> 200 each (a 4xx on a PURE single-variant groups baseline =
  Type1_IllegalSuccess — documented variant rejected on the groups face);
  SD/GD -> each 4xx (consistent enforcement) or 200 with fingerprint equal
  to exactly one pure baseline; mixed 2xx/4xx dispositions or different
  winners on the two faces = DEFECT_FOUND (Type4_StateLogicViolation);
  200 matching NEITHER pure baseline = SCRIPT_ERROR (unmeasured variant
  semantics); 5xx with /healthz alive = Type3_RuntimeFailure; transport
  with /healthz alive = Type3 hang, healthz down = SCRIPT_ERROR (constraint
  qdrant_behavioral_points_query_groups_001).
Constraint: qdrant_behavioral_points_query_groups_001 (bare id) —
  "grouping requires payload values for the group_by field; returns 200
  {groups: [{id, hits}]}; 400 on an invalid group_by; 404 for a missing
  collection" (evidence_tier: explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+query+groups -> POST /collections/{collection_name}/points/query/groups
  points+query        -> POST /collections/{collection_name}/points/query
  points+upsert       -> PUT  /collections/{collection_name}/points
  index+create        -> PUT  /collections/{collection_name}/index
  collections+create  -> PUT  /collections/{collection_name}
  collections+delete  -> DELETE /collections/{collection_name}
  healthz             -> GET  /healthz
  (wait is a query parameter on the upsert/index faces — passed via params=)
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
GRP = "grp"
V = [0.5, 0.25, 0.125, 0.0625]
# cluster A near +V (grp=a), cluster B near -V (grp=b): the two pure query
# variants necessarily rank the clusters in opposite order
SEED = [(1, "a", 1.01), (2, "a", 1.02), (3, "a", 1.03),
        (4, "b", -1.01), (5, "b", -1.02), (6, "b", -1.03)]


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


def transport_or_5xx(label, s, raw):
    """Returns True (with verdict printed) when the leg must stop; None = fine."""
    if s == -1:
        alive, _, _ = healthz_alive()
        if alive:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: request did "
                  f"not complete (transport error) while /healthz alive (hang/DoS): {str(raw)[:200]}")
        else:
            print("VERDICT: SCRIPT_ERROR — transport failure and healthz down")
        return True
    if 500 <= s <= 599:
        alive, _, _ = healthz_alive()
        if alive:
            print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — leg [{label}]: got {s} "
                  f"with service alive: {str(raw)[:300]}")
        else:
            print("VERDICT: SCRIPT_ERROR — 5xx and healthz down")
        return True
    return None


def extract_points_ids(body):
    """Ordered id list from a single-face QueryResponse (result.points[])."""
    if not isinstance(body, dict):
        return None
    result = body.get("result")
    pts = None
    if isinstance(result, dict):
        pts = result.get("points")
    elif isinstance(result, list):
        pts = result
    if not isinstance(pts, list):
        return None
    return [p.get("id") for p in pts if isinstance(p, dict)]


def extract_groups(body):
    """
    Locate the groups array in the response envelope.
    Contract response_shape: result (object) -> result.groups (array).
    """
    if not isinstance(body, dict):
        return None, "body-not-dict"
    result = body.get("result")
    if isinstance(result, dict):
        g = result.get("groups")
        return (g if isinstance(g, list) else None), "result.groups"
    if isinstance(result, list):
        return result, "result-array-observed"
    return None, "result-missing"


def groups_fp(groups):
    """Ordered grouped fingerprint [(group id, [hit ids in order])]."""
    fp = []
    for g in groups:
        if not isinstance(g, dict):
            fp.append(("<non-dict-group>", []))
            continue
        ids = [h.get("id") for h in (g.get("hits") or []) if isinstance(h, dict)]
        fp.append((g.get("id"), ids))
    return fp


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bqgsD" + tag

    # Arrange: own collection, own data, own cleanup
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": DIM, "distance": "Euclid"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    try:
        pts = [{"id": pid,
                "vector": [v * scale for v in V],
                "payload": {GRP: gval}} for pid, gval, scale in SEED]
        s, _, raw = safe_request("PUT", f"/collections/{coll}/points",
                                 json={"points": pts}, params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"setup upsert failed status={s}: {raw[:300]}")
            print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
            return
        s_ix, _, _ = safe_request("PUT", f"/collections/{coll}/index",
                                  json={"field_name": GRP, "field_schema": {"type": "keyword"}},
                                  params={"wait": "true"}, timeout=60)
        print(f"setup payload index on '{GRP}': status={s_ix} (best-effort, non-fatal)")

        single_path = f"/collections/{coll}/points/query"
        groups_path = f"/collections/{coll}/points/query/groups"
        nearest_q = {"nearest": V}
        recommend_q = {"recommend": {"positive": [5]}}
        dual_q = {"nearest": V, "recommend": {"positive": [5]}}

        # ---- Leg SN: single face pure nearest (live baseline) ----
        s, b, raw = safe_request("POST", single_path,
                                 json={"query": nearest_q, "limit": 6, "params": {"exact": True}},
                                 timeout=60)
        print(f"\nleg SN single-face pure-nearest -> status={s}")
        print(f"raw: {raw[:400]}")
        if transport_or_5xx("SN", s, raw):
            return
        FN = extract_points_ids(b) if s == 200 else None
        if s != 200 or FN is None:
            print(f"VERDICT: SCRIPT_ERROR — single-face pure-nearest baseline unusable ({s}); no defect conclusion")
            return
        print(f"leg SN OK: fingerprint FN = {FN}")

        # ---- Leg SR: single face pure recommend (live baseline) ----
        s, b, raw = safe_request("POST", single_path,
                                 json={"query": recommend_q, "limit": 6, "params": {"exact": True}},
                                 timeout=60)
        print(f"\nleg SR single-face pure-recommend -> status={s}")
        print(f"raw: {raw[:400]}")
        if transport_or_5xx("SR", s, raw):
            return
        FR = extract_points_ids(b) if s == 200 else None
        if s != 200 or FR is None:
            print(f"VERDICT: SCRIPT_ERROR — single-face pure-recommend baseline unusable ({s}); no defect conclusion")
            return
        if FN == FR:
            print(f"VERDICT: SCRIPT_ERROR — discrimination precondition failed (FN == FR = {FN}); "
                  f"the dual-key winner would be unreadable; no defect conclusion")
            return
        print(f"leg SR OK: fingerprint FR = {FR} (differs from FN — discriminating)")

        # ---- Leg GFN: groups face pure nearest ----
        s, b, raw = safe_request("POST", groups_path,
                                 json={"query": nearest_q, "group_by": GRP, "limit": 2,
                                       "group_size": 3, "params": {"exact": True}},
                                 timeout=60)
        print(f"\nleg GFN groups-face pure-nearest -> status={s}")
        print(f"raw: {raw[:400]}")
        if transport_or_5xx("GFN", s, raw):
            return
        groups, shape = extract_groups(b)
        if s in (400, 404, 422):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [GFN]: the pure "
                  f"single-variant nearest query (proven 200 on the single face) was rejected "
                  f"with {s} on the groups face: {raw[:300]}")
            return
        if s != 200 or groups is None:
            print(f"VERDICT: SCRIPT_ERROR — unexpected status/envelope {s} ({shape}); no defect conclusion")
            return
        GFN_fp = groups_fp(groups)
        print(f"leg GFN OK: grouped fingerprint GFN = {GFN_fp}")

        # ---- Leg GFR: groups face pure recommend ----
        s, b, raw = safe_request("POST", groups_path,
                                 json={"query": recommend_q, "group_by": GRP, "limit": 2,
                                       "group_size": 3, "params": {"exact": True}},
                                 timeout=60)
        print(f"\nleg GFR groups-face pure-recommend -> status={s}")
        print(f"raw: {raw[:400]}")
        if transport_or_5xx("GFR", s, raw):
            return
        groups, shape = extract_groups(b)
        if s in (400, 404, 422):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — leg [GFR]: the pure "
                  f"single-variant recommend query (proven 200 on the single face) was rejected "
                  f"with {s} on the groups face: {raw[:300]}")
            return
        if s != 200 or groups is None:
            print(f"VERDICT: SCRIPT_ERROR — unexpected status/envelope {s} ({shape}); no defect conclusion")
            return
        GFR_fp = groups_fp(groups)
        winner_detectable_groups = GFN_fp != GFR_fp
        print(f"leg GFR OK: grouped fingerprint GFR = {GFR_fp} "
              f"(groups-face winner detection: {'ON' if winner_detectable_groups else 'MASKED'})")

        # ---- Leg SD: single face DUAL-KEY query object ----
        s, b, raw = safe_request("POST", single_path,
                                 json={"query": dual_q, "limit": 6, "params": {"exact": True}},
                                 timeout=60)
        print(f"\nleg SD single-face dual-key -> status={s}")
        print(f"raw: {raw[:400]}")
        if transport_or_5xx("SD", s, raw):
            return
        sd_disp = None  # ("4xx", code) or ("2xx", winner or None)
        if 400 <= s <= 499:
            sd_disp = ("4xx", s)
            print(f"leg SD OK: dual-key REJECTED with {s} on the single face")
        elif s == 200:
            F = extract_points_ids(b)
            if F is None:
                print("VERDICT: SCRIPT_ERROR — SD 200 but no points array; no defect conclusion")
                return
            winner = "nearest" if F == FN else ("recommend" if F == FR else None)
            if winner is None:
                print(f"VERDICT: SCRIPT_ERROR — SD 200 matches NEITHER pure baseline "
                      f"(F={F}, FN={FN}, FR={FR}); unmeasured variant semantics, no defect conclusion")
                return
            sd_disp = ("2xx", winner)
            print(f"leg SD OK: dual-key ACCEPTED, '{winner}' variant won (second key dropped)")
        else:
            print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on SD; no defect conclusion")
            return

        # ---- Leg GD: groups face DUAL-KEY query object ----
        s, b, raw = safe_request("POST", groups_path,
                                 json={"query": dual_q, "group_by": GRP, "limit": 2,
                                       "group_size": 3, "params": {"exact": True}},
                                 timeout=60)
        print(f"\nleg GD groups-face dual-key -> status={s}")
        print(f"raw: {raw[:400]}")
        if transport_or_5xx("GD", s, raw):
            return
        gd_disp = None
        if 400 <= s <= 499:
            gd_disp = ("4xx", s)
            print(f"leg GD OK: dual-key REJECTED with {s} on the groups face")
        elif s == 200:
            groups, shape = extract_groups(b)
            if groups is None:
                print(f"VERDICT: SCRIPT_ERROR — GD 200 but no groups array ({shape}); no defect conclusion")
                return
            G = groups_fp(groups)
            winner = None
            if winner_detectable_groups:
                winner = "nearest" if G == GFN_fp else ("recommend" if G == GFR_fp else "?")
                if winner == "?":
                    print(f"VERDICT: SCRIPT_ERROR — GD 200 matches NEITHER groups baseline "
                          f"(G={G}); unmeasured variant semantics, no defect conclusion")
                    return
            gd_disp = ("2xx", winner)
            print(f"leg GD OK: dual-key ACCEPTED on the groups face"
                  f"{' (winner: ' + str(winner) + ')' if winner_detectable_groups else ' (winner masked by grouping)'}")
        else:
            print(f"VERDICT: SCRIPT_ERROR — unexpected status {s} on GD; no defect conclusion")
            return

        # ---- G9 cross-face adjudication ----
        print(f"\ncross-face disposition: single={sd_disp} groups={gd_disp}")
        if sd_disp[0] == "4xx" and gd_disp[0] == "4xx":
            print("VERDICT: NO_DEFECT — dual-key oneOf ambiguity consistently rejected on both faces")
        elif sd_disp[0] == "2xx" and gd_disp[0] == "2xx":
            sw, gw = sd_disp[1], gd_disp[1]
            if winner_detectable_groups and sw is not None and gw is not None and sw != gw:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — the SAME dual-key "
                      f"query object resolved to '{sw}' on the single face but '{gw}' on the "
                      f"groups face: cross-face inconsistent disposition of one payload")
            else:
                print(f"VERDICT: NO_DEFECT — dual-key tolerated on both faces with a consistent "
                      f"winner (R33/R40 family shape, read-face calibration; observed "
                      f"winner: single={sw}, groups={gw})")
        else:
            which = "groups" if sd_disp[0] == "2xx" else "single"
            other = "single" if sd_disp[0] == "2xx" else "groups"
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — the SAME dual-key query "
                  f"object was ACCEPTED on the {which} face but REJECTED on the {other} face "
                  f"({sd_disp} vs {gd_disp}): cross-face inconsistent disposition")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
