#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_query_groups_bounds_001
# strategy: strategy3 illegal-rejection attack (G4 positive-negative pairing:
#           min-1 closure must be ACCEPTED; 0/-1 must be REJECTED) on the
#           groups query face's documented bounds
# endpoint: points+query+groups
# constraint_ids: qdrant_range_points_query_groups_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points-groups
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — bounds declared in the
#            spec as "min 1" for BOTH group_size and limit; this script pins
#            the min-1 boundary closure (1 itself accepted, both params
#            optional-by-default accepted) against the violation set
#            {0, -1} which must draw a 4xx)
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy3 illegal_rejection (min-closure + violation pairing) x
  qdrant_range_points_query_groups_001 — the constraint pins
  "group_size minimum 1 (default 3 ...); limit minimum 1 (default 10)".
  G4 both-direction pairing in one run on the groups query face:
    P1 closure: group_size=1 AND limit=1 (the minima themselves) -> must be
       200 with a sane grouped result (exactly 1 group, at most 1 hit).
       A 4xx here = legal minimum wrongly rejected (Type1_IllegalRejection).
    P2 optional-by-default: group_size/limit both OMITTED (spec marks both
       optional with defaults) -> must be 200 (acceptance only; the default
       VALUES are adjudicated in semantics_001, not here).
    N1..N4 violations: group_size=0 / limit=0 / group_size=-1 / limit=-1
       -> each must draw a 4xx rejection. Any 200 = Type1_IllegalSuccess
       (accepting a value the spec pins below the minimum).
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
Oracle: P1 -> HTTP 200 with exactly 1 group carrying at most 1 hit (4xx =
  Type1_IllegalRejection DEFECT); P2 -> HTTP 200 (4xx = Type1_IllegalRejection
  DEFECT, both params documented optional); N1..N4 -> each HTTP 4xx (any 200
  = Type1_IllegalSuccess DEFECT — minimum-1 bound bypassed); 5xx with
  /healthz alive = Type3_RuntimeFailure; transport failure -> /healthz
  liveness re-check then SCRIPT_ERROR (constraint
  qdrant_range_points_query_groups_001).
Constraint: qdrant_range_points_query_groups_001 — "group_size minimum 1
  (default 3, max points per group); limit minimum 1 (default 10, max amount
  of groups)" (evidence_tier: explicit; level: endpoint)

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
ANCHOR = [0.0, 10.0, 10.0, 10.0]  # distance to [d,10,10,10] == d exactly (Euclid)

# 12 groups: g01..g03 rich (4 points each), g04..g12 singletons
SEED = []
for gi, d0 in ((1, 0.0), (2, 0.5), (3, 1.0)):
    for k in range(4):
        d = d0 + 0.1 * k
        SEED.append({"id": gi * 1000 + 100 + k, "vector": [d] + BASE3,
                     "payload": {"grp": "g%02d" % gi, "val": d}})
for gi in range(4, 13):
    d = float(gi)
    SEED.append({"id": 1400 + gi, "vector": [d] + BASE3,
                 "payload": {"grp": "g%02d" % gi, "val": d}})


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
    """Groups-face extraction (response_shape: result.groups array)."""
    if isinstance(body, dict):
        r = body.get("result")
        if isinstance(r, dict) and isinstance(r.get("groups"), list):
            return r["groups"]
    return None


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "spqgB1" + tag
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

        def leg(name, extra):
            body = {"query": {"nearest": ANCHOR}, "group_by": "grp",
                    "params": {"exact": True}, "with_payload": False}
            body.update(extra)
            body = {k: v for k, v in body.items() if v is not None}
            rs, rbody, rraw = safe_request("POST", qpath, json=body, timeout=60)
            print(f"[{name}] status={rs} raw: {rraw[:400]}")
            if rs == -1:
                bail_transport(name)
                return "BAIL"
            if handle_5xx(rs, rraw, name):
                return "STOP"
            return rs, groups_of(rbody)

        # ---- P1: min closure (group_size=1 AND limit=1) must be ACCEPTED ----
        out = leg("P1 group_size=1 limit=1", {"group_size": 1, "limit": 1})
        if out in ("BAIL", "STOP"):
            return
        rs, groups = out
        if not (200 <= rs <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) — the documented "
                  f"minima group_size=1/limit=1 (spec: 'minimum 1') got status={rs}; "
                  f"legal boundary closure rejected")
            return
        n_groups = len(groups) if groups is not None else -1
        n_hits0 = len(groups[0].get("hits", [])) if groups and isinstance(groups[0], dict) else -1
        print(f"P1 groups={n_groups} first-group-hits={n_hits0}")
        if n_groups != 1 or not (0 <= n_hits0 <= 1):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — P1 accepted "
                  f"but limit=1 returned {n_groups} groups and group_size=1 returned "
                  f"{n_hits0} hits in the first group (constraint: limit = max amount "
                  f"of groups, group_size = max points per group)")
            return

        # ---- P2: both params OMITTED (optional per spec) must be ACCEPTED ----
        out = leg("P2 defaults omitted", {"group_size": None, "limit": None})
        if out in ("BAIL", "STOP"):
            return
        rs, groups = out
        if not (200 <= rs <= 299):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) — omitting both "
                  f"optional params (spec marks group_size/limit optional with "
                  f"defaults 3/10) got status={rs}")
            return
        if not groups:
            print("VERDICT: SCRIPT_ERROR — P2 returned 200 but no parsable groups; no defect conclusion")
            return
        print(f"P2 groups returned={len(groups)} (acceptance leg only; default values adjudicated in semantics_001)")

        # ---- N1..N4: below-minimum values must be REJECTED ----
        for name, extra in (("N1 group_size=0", {"group_size": 0, "limit": 2}),
                            ("N2 limit=0", {"group_size": 2, "limit": 0}),
                            ("N3 group_size=-1", {"group_size": -1, "limit": 2}),
                            ("N4 limit=-1", {"group_size": 2, "limit": -1})):
            out = leg(name, extra)
            if out in ("BAIL", "STOP"):
                return
            rs, _ = out
            if 200 <= rs <= 299:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {name} "
                      f"accepted with status={rs}; constraint pins 'minimum 1' "
                      f"for both group_size and limit")
                return
            if not (400 <= rs <= 499):
                print(f"VERDICT: SCRIPT_ERROR — {name} unexpected status {rs}; no defect conclusion")
                return
            print(f"{name} rejected with {rs} (bound enforced)")

        print("min-1 closure accepted, optional-defaults accepted, 0/-1 rejected on all legs")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
