#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_query_groups_offset_faces_001
# strategy: strategy6 metamorphic cross-face (G9) attack — the SAME offset
#           payload sent to all THREE documented groups faces (query /
#           legacy search / legacy recommend); the constraint pins the SAME
#           restriction on all three
# endpoint: points+query+groups
# constraint_ids: qdrant_state_points_query_groups_001
# source_url: https://qdrant.tech/documentation/search/search/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-05 (Documentation Drift — "the same restriction applies to
#            the legacy search/recommend groups variants" is an explicit
#            cross-face promise; a face that silently honors offset while
#            its siblings reject/omit it gives clients undocumented and
#            inconsistent pagination semantics)
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy6 metamorphic cross-face G9 x
  qdrant_state_points_query_groups_001 — "the groups query API does not
  allow offset (pagination); the same restriction applies to the legacy
  search/recommend groups variants [DOC search]". Per face F in
  {query/groups, search/groups, recommend/groups}:
    C_F  control (face-native body, NO offset)  -> must be 200; fingerprint
         PF measured LIVE (no assumed ranking; recommend-face by-id
         exclusion of the positive point is absorbed by the live baseline)
    O_F  control body + offset=1 -> licensed: 4xx (reject) OR 200 with
         fingerprint == PF (omit); UNLICENSED: 200 with fingerprint != PF
         (honored pagination)
  Adjudication: any usable face honoring offset = DEFECT (Type4) on its own;
  otherwise all-reject or all-omit = NO_DEFECT; a MIX of reject and omit
  across faces = both dispositions individually licensed by the constraint,
  recorded as a G9 NOTE for the judge (no defect claim).
  A face whose control fails is marked unusable (NOTE) and excluded — its
  failure is a fixture issue, not a defect claim.
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
Oracle: every C_F -> HTTP 200 (non-200 control = face unusable, NOTE only);
  every O_F -> 4xx or 200 with fingerprint == that face's own live control
  fingerprint; ANY usable face returning 200 with a shifted fingerprint =
  DEFECT_FOUND (Type4_StateLogicViolation) — offset honored as pagination
  on a groups face whose docs say pagination is not available; all-usable
  faces landing in {reject} or {omit} -> NO_DEFECT; mixed reject/omit ->
  NO_DEFECT + G9 NOTE; 5xx with /healthz alive = Type3_RuntimeFailure;
  transport failure -> /healthz liveness re-check then SCRIPT_ERROR
  (constraint qdrant_state_points_query_groups_001).
Constraint: qdrant_state_points_query_groups_001 — "the groups query API
  does not allow offset (pagination); the same restriction applies to the
  legacy search/recommend groups variants [DOC search]" (evidence_tier:
  explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  points+query+groups     -> POST /collections/{collection_name}/points/query/groups
  points+search+groups    -> POST /collections/{collection_name}/points/search/groups
  points+recommend+groups -> POST /collections/{collection_name}/points/recommend/groups
  points+upsert           -> PUT  /collections/{collection_name}/points
  collections+create      -> PUT  /collections/{collection_name}
  collections+delete      -> DELETE /collections/{collection_name}
  field index create      -> PUT  /collections/{collection_name}/index
  healthz                 -> GET  /healthz
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


def fingerprint(groups):
    return [g.get("id") for g in groups or [] if isinstance(g, dict)]


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "spqgF1" + tag

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

        # Face-native request bodies (all with group_by/group_size/limit/params)
        FACES = {
            "query/groups": (
                f"/collections/{coll}/points/query/groups",
                {"query": {"nearest": ANCHOR}}),
            "search/groups": (
                f"/collections/{coll}/points/search/groups",
                {"vector": ANCHOR}),
            "recommend/groups": (
                f"/collections/{coll}/points/recommend/groups",
                {"positive": [1101]}),
        }

        results = {}
        for face, (path, core) in FACES.items():
            def call(name, offset):
                body = dict(core)
                body.update({"group_by": "grp", "group_size": 2, "limit": 3,
                             "params": {"exact": True}})
                if offset is not None:
                    body["offset"] = offset
                rs, rbody, rraw = safe_request("POST", path, json=body, timeout=60)
                print(f"[{name}] status={rs} raw: {rraw[:400]}")
                if rs == -1:
                    bail_transport(name)
                    return "BAIL"
                if handle_5xx(rs, rraw, name):
                    return "STOP"
                if 200 <= rs <= 299:
                    return ("accept", fingerprint(groups_of(rbody)))
                if 400 <= rs <= 499:
                    return ("reject", None)
                print(f"VERDICT: SCRIPT_ERROR — {name} unexpected status {rs}")
                return "STOP"

            out = call(f"{face} control", None)
            if out in ("BAIL", "STOP"):
                return
            disp, pf = out
            if disp != "accept":
                print(f"NOTE face {face}: control not accepted ({disp}); face "
                      f"marked unusable, excluded from adjudication")
                results[face] = "unusable"
                continue
            print(f"{face} control fingerprint = {pf}")

            out = call(f"{face} offset=1", 1)
            if out in ("BAIL", "STOP"):
                return
            disp, pfo = out
            if disp == "reject":
                print(f"{face}: offset=1 rejected (4xx) — licensed 'reject' branch")
                results[face] = "reject"
            elif pfo == pf:
                print(f"{face}: offset=1 accepted but result invariant — licensed "
                      f"'omit' branch")
                results[face] = "omit"
            else:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — face "
                      f"{face} HONORED offset=1 as pagination: control groups {pf} "
                      f"-> offset groups {pfo}; the constraint pins that groups "
                      f"endpoints reject/omit offset (pagination is not available "
                      f"with groups) and the SAME restriction on the legacy "
                      f"variants")
                return

        usable = {f: d for f, d in results.items() if d != "unusable"}
        if not usable:
            print("VERDICT: SCRIPT_ERROR — no usable face; no defect conclusion")
            return
        dispositions = set(usable.values())
        if len(dispositions) > 1:
            print(f"NOTE G9: mixed licensed dispositions across faces {usable} — "
                  f"the constraint allows either per face, but the asymmetry is "
                  f"recorded for the judge")
        print(f"face dispositions = {usable}")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
