#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_query_groups_typecoerce_001
# strategy: strategy4 implicit-type-conversion attack on the integer-typed
#           groups bounds (group_size / limit declared integer min 1)
# endpoint: points+query+groups
# constraint_ids: qdrant_range_points_query_groups_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points-groups
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust — the spec types group_size
#            and limit as integer; if the REST layer coerces JSON strings /
#            floats / booleans into that integer the documented bound loses
#            its meaning: "2" or true or 2.0 would silently mean 2)
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy4 type_coercion x qdrant_range_points_query_groups_001 —
  the constraint types both bounds as integers ("group_size minimum 1
  (default 3 ...); limit minimum 1 (default 10)"). Six coercion probes on
  the groups query face, each holding the OTHER param at a legal integer 2
  so only the type of the probed param varies:
    C  control : group_size=2, limit=2 (plain ints)          -> must be 200
    T1 group_size="2" (string), T2 group_size=2.0 (float),
    T3 group_size=true (bool), T4 limit="2", T5 limit=2.0, T6 limit=true
  Each T leg must draw a 4xx (the schema type is integer; a non-integer
  JSON value is a validation error). A 200 on any T leg =
  Type1_IllegalSuccess — implicit coercion of a string/float/bool into the
  integer bound. Intra-family asymmetries (e.g. 2.0 accepted while "2"
  rejected) are recorded as G9 NOTEs for the judge.
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
Oracle: C -> HTTP 200 (else the fixture is unusable, SCRIPT_ERROR); T1..T6 ->
  each HTTP 4xx (any single 200 = Type1_IllegalSuccess DEFECT — string/
  float/bool coerced into the integer-typed bound); asymmetric dispositions
  within the same family recorded as G9 NOTE but do not alone flip the
  verdict; 5xx with /healthz alive = Type3_RuntimeFailure; transport
  failure -> /healthz liveness re-check then SCRIPT_ERROR (constraint
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


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "spqgT1" + tag
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

        def probe(name, gs, lim):
            body = {"query": {"nearest": ANCHOR}, "group_by": "grp",
                    "params": {"exact": True}, "group_size": gs, "limit": lim}
            rs, _, rraw = safe_request("POST", qpath, json=body, timeout=60)
            print(f"[{name}] status={rs} raw: {rraw[:400]}")
            if rs == -1:
                bail_transport(name)
                return "BAIL"
            if handle_5xx(rs, rraw, name):
                return "STOP"
            if 200 <= rs <= 299:
                return "accept"
            if 400 <= rs <= 499:
                return "reject"
            return "odd:%d" % rs

        out = probe("C control group_size=2 limit=2", 2, 2)
        if out in ("BAIL", "STOP"):
            return
        if out != "accept":
            print(f"VERDICT: SCRIPT_ERROR — control leg not accepted ({out}); fixture unusable")
            return
        print("control accepted (value 2 legal on both params)")

        dispositions = {}
        legs = (("T1 group_size='2'", "2", 2), ("T2 group_size=2.0", 2.0, 2),
                ("T3 group_size=true", True, 2), ("T4 limit='2'", 2, "2"),
                ("T5 limit=2.0", 2, 2.0), ("T6 limit=true", 2, True))
        for name, gs, lim in legs:
            out = probe(name, gs, lim)
            if out in ("BAIL", "STOP"):
                return
            dispositions[name] = out
            if out == "accept":
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {name} "
                      f"accepted with HTTP 200: a non-integer JSON value was "
                      f"implicitly coerced into the integer-typed bound "
                      f"(constraint: group_size/limit minimum 1, type integer)")
                return
            if out != "reject":
                print(f"VERDICT: SCRIPT_ERROR — {name} unexpected disposition {out}")
                return

        fam = {}
        for name, d in dispositions.items():
            kind = "string" if "'2'" in name else ("float" if "2.0" in name else "bool")
            fam.setdefault(kind, set()).add(d)
        asym = [k for k, v in fam.items() if len(v) > 1] if len(set(map(str, fam.values()))) > 1 else []
        if asym:
            print(f"NOTE G9: asymmetric disposition across the coercion family: "
                  f"{dispositions} (recorded for the judge; each leg was still "
                  f"correctly rejected)")
        print(f"all six non-integer probes rejected; dispositions={dispositions}")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=60)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
