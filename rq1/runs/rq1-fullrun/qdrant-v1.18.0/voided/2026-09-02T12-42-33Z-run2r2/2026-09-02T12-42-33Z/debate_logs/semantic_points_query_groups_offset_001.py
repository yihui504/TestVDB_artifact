#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_query_groups_offset_001
# strategy: strategy6 metamorphic-relation attack — result INVARIANCE under
#           the addition of an `offset` key the docs say groups do not
#           support ("pagination is not available with groups")
# endpoint: points+query+groups
# constraint_ids: qdrant_state_points_query_groups_001
# source_url: https://qdrant.tech/documentation/search/search/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-05 (Documentation Drift — the contract records an explicit
#            DOC promise that groups endpoints reject/omit offset pagination;
#            an implementation that quietly honors offset would offer
#            undocumented, likely-broken pagination: skipping N GROUPS, not
#            points, with no next_page_offset contract)
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy6 metamorphic x qdrant_state_points_query_groups_001 —
  "groups endpoints reject/omit offset pagination; pagination is not
  available with groups". The endpoint's published parameter set carries NO
  offset parameter, so a client sending one is off-contract in exactly the
  way the DOC promise addresses. Metamorphic legs on the query/groups face:
    B  control: group_size=2, limit=3, NO offset -> 200, fingerprint F0
       ([(gid, hit ids)] over the 3 best groups)
    O1 B + offset=1   -> licensed dispositions: 4xx (reject) OR 200 with
       fingerprint == F0 (omit/ignore). UNLICENSED: 200 with a fingerprint
       != F0 (e.g. groups g02,g03,g04 = the first group skipped) meaning
       offset is being honored as real pagination.
    O2 B + offset=100 -> same adjudication (honoring would empty or shift
       the window); NOTE next_page_offset key presence in any 200 body —
       a pagination affordance in the response would corroborate honored
       pagination.
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
Oracle: B -> HTTP 200 with a 3-group fingerprint F0 (else SCRIPT_ERROR —
  fixture unusable); O1/O2 -> each either 4xx (reject) or 200 with
  fingerprint EXACTLY == F0 (omit); any 200 whose fingerprint differs from
  F0 = DEFECT_FOUND (Type4_StateLogicViolation) — offset honored as
  pagination the docs say is not available with groups; a non-null
  next_page_offset observed alongside an accepted-and-shifted offset is
  recorded as corroborating evidence; 5xx with /healthz alive =
  Type3_RuntimeFailure; transport failure -> /healthz liveness re-check then
  SCRIPT_ERROR (constraint qdrant_state_points_query_groups_001).
Constraint: qdrant_state_points_query_groups_001 — "the groups query API
  does not allow offset (pagination); the same restriction applies to the
  legacy search/recommend groups variants [DOC search]" (evidence_tier:
  explicit; level: endpoint)

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


def fingerprint(groups):
    return [(g.get("id"), [h.get("id") for h in (g.get("hits") or [])
                           if isinstance(h, dict)])
            for g in groups or [] if isinstance(g, dict)]


def next_page_offset_of(body):
    if isinstance(body, dict):
        r = body.get("result")
        if isinstance(r, dict) and "next_page_offset" in r:
            return r.get("next_page_offset")
    return "<absent>"


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "spqgO1" + tag
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
        s, _, raw = safe_request("PUT", f"/collections/{coll}/index",
                                 json={"field_name": "grp", "field_schema": "keyword"},
                                 params={"wait": "true"}, timeout=60)
        if s not in (200, 201):
            print(f"NOTE setup: grp index create returned {s}: {raw[:200]}")

        def run(name, offset):
            body = {"query": {"nearest": ANCHOR}, "group_by": "grp",
                    "params": {"exact": True}, "group_size": 2, "limit": 3}
            if offset is not None:
                body["offset"] = offset
            rs, rbody, rraw = safe_request("POST", qpath, json=body, timeout=60)
            print(f"[{name}] status={rs} raw: {rraw[:500]}")
            if rs == -1:
                bail_transport(name)
                return "BAIL"
            if handle_5xx(rs, rraw, name):
                return "STOP"
            if 200 <= rs <= 299:
                return ("accept", fingerprint(groups_of(rbody)),
                        next_page_offset_of(rbody))
            if 400 <= rs <= 499:
                return ("reject", None, None)
            print(f"VERDICT: SCRIPT_ERROR — {name} unexpected status {rs}")
            return "STOP"

        # ---- B: control without offset ----
        out = run("B control no offset", None)
        if out in ("BAIL", "STOP"):
            return
        disp, f0, npo = out
        if disp != "accept":
            print("VERDICT: SCRIPT_ERROR — control leg not accepted; fixture unusable")
            return
        print(f"B fingerprint F0 = {f0} (next_page_offset={npo})")
        if not f0 or len(f0) != 3:
            print("VERDICT: SCRIPT_ERROR — control returned unexpected shape; fixture unusable")
            return

        # ---- O1: offset=1 ----
        out = run("O1 offset=1", 1)
        if out in ("BAIL", "STOP"):
            return
        disp, fp, npo = out
        if disp == "reject":
            print("O1 rejected (4xx) — licensed 'reject' branch")
        else:
            print(f"O1 accepted, fingerprint = {fp} (next_page_offset={npo})")
            if fp != f0:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — adding "
                      f"offset=1 CHANGED the groups result: {f0} -> {fp}; offset is "
                      f"honored as pagination on an endpoint whose documentation "
                      f"states pagination is NOT available with groups "
                      f"(constraint qdrant_state_points_query_groups_001)"
                      + (f"; corroborating non-null next_page_offset={npo}"
                         if npo not in ("<absent>", None) else ""))
                return
            if npo not in ("<absent>", None):
                print(f"NOTE O1: response carries next_page_offset={npo} while "
                      f"results were offset-invariant — recorded for the judge")

        # ---- O2: offset=100 ----
        out = run("O2 offset=100", 100)
        if out in ("BAIL", "STOP"):
            return
        disp, fp, npo = out
        if disp == "reject":
            print("O2 rejected (4xx) — licensed 'reject' branch")
        else:
            print(f"O2 accepted, fingerprint = {fp} (next_page_offset={npo})")
            if fp != f0:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — adding "
                      f"offset=100 CHANGED the groups result: {f0} -> {fp}; offset is "
                      f"honored as pagination on an endpoint whose documentation "
                      f"states pagination is NOT available with groups "
                      f"(constraint qdrant_state_points_query_groups_001)")
                return

        print("offset key never shifted the grouped result (reject-or-omit only) — "
              "metamorphic invariance holds")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
