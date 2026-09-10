#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_query_groups_filter_001
# strategy: strategy7 filter-parameter semantic correctness on the groups
#           face — exact-set closure over a fixture where every group is
#           entirely inside or outside each filter, so the oracle is
#           interpretation-independent (filter-before-group vs
#           filter-after-group must agree)
# endpoint: points+query+groups
# constraint_ids: qdrant_behavioral_points_query_groups_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points-groups
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift — the universal query API documents
#            a filter on the groups request; if the filter is ignored,
#            mis-scoped, or bleeds between groups on this face, clients get
#            silently wrong grouped results)
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy7 filter_semantics x
  qdrant_behavioral_points_query_groups_001 (valid group query must return
  the right groups) — a filter inside the groups request must preserve
  documented filter semantics. Fixture hygiene: each leg's filter puts
  WHOLE groups in or out (never splits a group), so any correct
  implementation (filter points then group, or group then filter groups)
  yields the identical expected set — the oracle is
  interpretation-independent. Legs (exact search ON):
    F1 must match grp == g02          -> EXACTLY 1 group [g02], hits
       {1201,1202,1203,1204}
    F2 must match grp in [g01,g03]    -> EXACTLY groups {g01,g03}, each all
       4 hits
    F3 must_not grp == g02, limit=3, group_size=1 -> EXACTLY the 3 best
       remaining groups [g01,g03,g04] (exclusion narrows, ranking survives)
    F4 must range val < 0.5 (only g01's 4 points qualify; 0.5 itself is
       g02's floor and must stay excluded) -> EXACTLY 1 group [g01] with
       all 4 hits
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
Oracle: F1 -> 200, group id list exactly ['g02'], hit id set exactly
  {1201,1202,1203,1204}; F2 -> 200, group id set exactly {g01,g03}, each
  with its full 4-point hit set; F3 -> 200, group ids in rank order exactly
  ['g01','g03','g04'] with 1 hit each; F4 -> 200, group ids exactly ['g01']
  with hit set {1101,1102,1103,1104} (strict lt: g02's val 0.5 excluded);
  any extra group, missing group, or wrong hit set =
  DEFECT_FOUND (Type4_StateLogicViolation) — filter not applied / mis-
  scoped / bleeding on the groups face; 5xx with /healthz alive =
  Type3_RuntimeFailure; transport failure -> /healthz liveness re-check
  then SCRIPT_ERROR (constraint qdrant_behavioral_points_query_groups_001).
Constraint: qdrant_behavioral_points_query_groups_001 — "grouping requires
  payload values for the group_by field; returns 200 {groups: [{id,
  hits}]}; 400 on an invalid group_by; 404 for a missing collection"
  (evidence_tier: explicit; level: endpoint); filter semantics per the
  vendored Filter schema in request_required_paths (filter.must.key /
  filter.must_not.key / match / range)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+query+groups -> POST /collections/{collection_name}/points/query/groups
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
ANCHOR = [0.0, 10.0, 10.0, 10.0]

SEED = []
for gi, d0 in ((1, 0.0), (2, 0.5), (3, 1.0)):
    for k in range(4):
        d = d0 + 0.1 * k
        SEED.append({"id": gi * 1000 + 100 + k, "vector": [d] + BASE3,
                     "payload": {"grp": "g%02d" % gi, "val": d}})
for gi in range(4, 13):
    SEED.append({"id": 1400 + gi, "vector": [float(gi)] + BASE3,
                 "payload": {"grp": "g%02d" % gi, "val": float(gi)}})


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


def fp(groups):
    return [(g.get("id"), sorted(h.get("id") for h in (g.get("hits") or [])
                                 if isinstance(h, dict)))
            for g in groups or [] if isinstance(g, dict)]


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "spqgL1" + tag
    qpath = f"/collections/{coll}/points/query/groups"

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
        for fld, schema in (("grp", "keyword"), ("val", "float")):
            s, _, raw = safe_request("PUT", f"/collections/{coll}/index",
                                     json={"field_name": fld, "field_schema": schema},
                                     params={"wait": "true"}, timeout=60)
            if s not in (200, 201):
                print(f"NOTE setup: {fld} index create returned {s}: {raw[:200]}")

        def run(name, flt, group_size, limit):
            body = {"query": {"nearest": ANCHOR}, "group_by": "grp",
                    "params": {"exact": True}, "filter": flt,
                    "group_size": group_size, "limit": limit}
            rs, rbody, rraw = safe_request("POST", qpath, json=body, timeout=60)
            print(f"[{name}] status={rs} raw: {rraw[:500]}")
            if rs == -1:
                bail_transport(name)
                return "BAIL"
            if handle_5xx(rs, rraw, name):
                return "STOP"
            if not (200 <= rs <= 299):
                print(f"VERDICT: SCRIPT_ERROR — {name} unexpected status {rs}; no defect conclusion")
                return "STOP"
            return fp(groups_of(rbody))

        # ---- F1: equality filter -> exactly g02 with all 4 hits ----
        got = run("F1 must grp==g02",
                  {"must": [{"key": "grp", "match": {"value": "g02"}}]}, 4, 12)
        if got in ("BAIL", "STOP"):
            return
        print(f"F1 fingerprint = {got}")
        if got != [("g02", [1201, 1202, 1203, 1204])]:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F1 equality "
                  f"filter must yield exactly group g02 with hits 1201..1204, got "
                  f"{got} (filter ignored / mis-scoped / hit-set wrong on the "
                  f"groups face)")
            return

        # ---- F2: membership filter -> exactly {g01, g03} ----
        got = run("F2 must grp in [g01,g03]",
                  {"must": [{"key": "grp", "match": {"any": ["g01", "g03"]}}]}, 4, 12)
        if got in ("BAIL", "STOP"):
            return
        print(f"F2 fingerprint = {got}")
        exp = [("g01", [1101, 1102, 1103, 1104]), ("g03", [1301, 1302, 1303, 1304])]
        if sorted(got) != sorted(exp):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F2 "
                  f"membership filter must yield exactly groups g01 and g03 with "
                  f"their full hit sets, got {got}")
            return

        # ---- F3: must_not exclusion -> top-3 remaining groups [g01,g03,g04] ----
        got = run("F3 must_not grp==g02",
                  {"must_not": [{"key": "grp", "match": {"value": "g02"}}]}, 1, 3)
        if got in ("BAIL", "STOP"):
            return
        print(f"F3 fingerprint = {got}")
        if [g[0] for g in got] != ["g01", "g03", "g04"]:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F3 must_not "
                  f"g02 with limit=3 must yield exactly the 3 best remaining "
                  f"groups ['g01','g03','g04'], got {got}")
            return

        # ---- F4: range filter val < 0.5 -> exactly g01 (strict lt keeps g02 out) ----
        got = run("F4 must range val<0.5",
                  {"must": [{"key": "val", "range": {"lt": 0.5}}]}, 4, 12)
        if got in ("BAIL", "STOP"):
            return
        print(f"F4 fingerprint = {got}")
        if got != [("g01", [1101, 1102, 1103, 1104])]:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — F4 range "
                  f"val<0.5 must yield exactly group g01 (its 4 points are the "
                  f"only vals below 0.5; g02's floor 0.5 excluded by strict lt), "
                  f"got {got}")
            return

        print("F1/F2/F3/F4 exact-set closures all hold on the groups face")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
