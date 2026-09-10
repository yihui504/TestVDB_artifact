#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_query_groups_diag_001
# strategy: strategy2 error-diagnostics quality attack (Type-2, Round-2+
#           focus) — grading the MESSAGE of the groups face's two documented
#           rejection channels plus the bound-violation channel
# endpoint: points+query+groups
# constraint_ids: qdrant_behavioral_points_query_groups_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points-groups
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-02 (Error Message Negligence — the assertion pins the STATUS
#            faces (400 invalid group_by / 404 missing collection);
#            behavior_001 owns the status oracle, this script grades WHAT
#            the rejections TELL the user: named parameter, format hint,
#            actionable fix)
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy2 diagnosis_quality (Type2) x
  qdrant_behavioral_points_query_groups_001 — the assertion carries explicit
  error promises ("400 on an invalid group_by; 404 for a missing
  collection"); the status legs are owned by behavior_001 (and the
  group_size bound by bounds_001), so this script grades the MESSAGE
  quality of three rejection channels with the 3-point rubric (criterion 1:
  parameter named; criterion 2: format/range hint; criterion 3: actionable
  suggestion):
    D1 invalid group_by (field with no payload values) -> 4xx; grade
       against expected_param group_by
    D2 missing collection -> 404; grade: the collection name or the word
       'collection' named, context hint, actionable
    D3 group_size=0 (below the documented minimum 1; secondary anchor
       qdrant_range_points_query_groups_001) -> 4xx; grade against
       expected_param group_size (bound hint e.g. minimum/at least 1)
  A 2xx on any leg has no message to grade — recorded as NOTE cross-ref to
  the script owning that status oracle; no duplicate adjudication.
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
Oracle: D1 -> 4xx whose message scores >= 1/3 on the rubric (0/3 =
  Type2_PoorDiagnostics DEFECT; 2xx = NOTE, status oracle owned by
  behavior_001); D2 -> EXACTLY 404 with message scoring >= 1/3 (0/3 = Type2
  DEFECT; 2xx or non-404 4xx = NOTE, status oracle owned by behavior_001);
  D3 -> 4xx with message scoring >= 1/3 (0/3 = Type2 DEFECT; 2xx = NOTE,
  status oracle owned by bounds_001); a leg grading 0/3 on ANY channel =
  DEFECT_FOUND (Type2_PoorDiagnostics); all graded channels >= 1/3 ->
  NO_DEFECT with scores reported; 5xx with /healthz alive =
  Type3_RuntimeFailure; transport failure -> /healthz liveness re-check
  then SCRIPT_ERROR (constraint qdrant_behavioral_points_query_groups_001).
Constraint: qdrant_behavioral_points_query_groups_001 — "grouping requires
  payload values for the group_by field; returns 200 {groups: [{id,
  hits}]}; 400 on an invalid group_by; 404 for a missing collection"
  (evidence_tier: explicit; level: endpoint); secondary anchor
  qdrant_range_points_query_groups_001 ("group_size minimum 1")

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


def check_error_quality(body, expected_terms):
    """
    Type-2 diagnosis quality rubric (body may be dict/str).
    - Criterion 1: parameter/resource named (any expected term present)
    - Criterion 2: format/range hint
    - Criterion 3: actionable suggestion
    Returns (score, max_score).
    """
    error_msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()
    score = 0
    max_score = 3

    if any(t.lower() in error_msg for t in expected_terms):
        score += 1

    format_hints = ["must be", "expected", "should be", "valid", "range",
                    "type", "positive", "non-zero", "minimum", "at least",
                    "min 1", "greater"]
    if any(hint in error_msg for hint in format_hints):
        score += 1

    action_hints = ["correct", "try", "use", "change", "specify", "provide",
                    "create", "check", "exists"]
    if any(hint in error_msg for hint in action_hints):
        score += 1

    return score, max_score


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "spqgD1" + tag
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

        absent = "spqg_absent_" + tag

        def fire(name, path, body):
            rs, rbody, rraw = safe_request("POST", path, json=body, timeout=60)
            print(f"[{name}] status={rs} raw: {rraw[:400]}")
            if rs == -1:
                bail_transport(name)
                return "BAIL"
            if handle_5xx(rs, rraw, name):
                return "STOP"
            return rs, rbody

        base_body = {"query": {"nearest": ANCHOR}, "group_by": "grp",
                     "params": {"exact": True}, "group_size": 2, "limit": 5}

        scores = {}

        # ---- D1: invalid group_by message quality ----
        b = dict(base_body, group_by="no_such_field_zz")
        out = fire("D1 invalid group_by", qpath, b)
        if out in ("BAIL", "STOP"):
            return
        rs, rbody = out
        if 200 <= rs <= 299:
            print("NOTE D1: 2xx — status oracle owned by behavior_001 I1; nothing to grade")
        elif 400 <= rs <= 499:
            sc, mx = check_error_quality(rbody, ["group_by", "no_such_field_zz"])
            scores["D1"] = (sc, mx)
            print(f"D1 message score {sc}/{mx}")
            if sc == 0:
                print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — D1 invalid "
                      f"group_by rejected ({rs}) but the message names neither the "
                      f"parameter (group_by) nor the offending field, gives no "
                      f"format hint and no actionable fix: {str(rbody)[:250]}")
                return
        else:
            print(f"VERDICT: SCRIPT_ERROR — D1 unexpected status {rs}")
            return

        # ---- D2: missing collection message quality ----
        out = fire("D2 missing collection", f"/collections/{absent}/points/query/groups", base_body)
        if out in ("BAIL", "STOP"):
            return
        rs, rbody = out
        if rs == 404:
            sc, mx = check_error_quality(rbody, [absent, "collection"])
            scores["D2"] = (sc, mx)
            print(f"D2 message score {sc}/{mx}")
            if sc == 0:
                print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — D2 missing "
                      f"collection answered 404 but the message names neither the "
                      f"collection ('{absent}') nor the word 'collection', gives no "
                      f"hint and no fix: {str(rbody)[:250]}")
                return
        elif 200 <= rs <= 299:
            print("NOTE D2: 2xx — status oracle owned by behavior_001 M; nothing to grade")
        elif 400 <= rs <= 499:
            print("NOTE D2: non-404 4xx — status oracle owned by behavior_001 M; "
                  f"message still graded for information")
            sc, mx = check_error_quality(rbody, [absent, "collection"])
            scores["D2"] = (sc, mx)
            print(f"D2 message score {sc}/{mx} (status face separately owned)")
            if sc == 0:
                print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — D2 message "
                      f"scored 0/3 on top of the wrong status: {str(rbody)[:250]}")
                return
        else:
            print(f"VERDICT: SCRIPT_ERROR — D2 unexpected status {rs}")
            return

        # ---- D3: group_size=0 message quality (secondary anchor: range constraint) ----
        b = dict(base_body, group_size=0)
        out = fire("D3 group_size=0", qpath, b)
        if out in ("BAIL", "STOP"):
            return
        rs, rbody = out
        if 200 <= rs <= 299:
            print("NOTE D3: 2xx — status oracle owned by bounds_001 N1; nothing to grade")
        elif 400 <= rs <= 499:
            sc, mx = check_error_quality(rbody, ["group_size"])
            scores["D3"] = (sc, mx)
            print(f"D3 message score {sc}/{mx}")
            if sc == 0:
                print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — D3 "
                      f"group_size=0 rejected ({rs}) but the message names no "
                      f"parameter, no bound (minimum 1) and no fix: {str(rbody)[:250]}")
                return
        else:
            print(f"VERDICT: SCRIPT_ERROR — D3 unexpected status {rs}")
            return

        print(f"all graded channels >= 1/3; scores = {scores}")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal
        try:
            safe_request("DELETE", f"/collections/spqg_absent_{tag}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
