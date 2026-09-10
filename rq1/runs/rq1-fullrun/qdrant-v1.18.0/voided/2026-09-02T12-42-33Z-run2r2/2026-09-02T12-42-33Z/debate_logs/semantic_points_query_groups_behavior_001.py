#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_points_query_groups_behavior_001
# strategy: strategy1 behavioral-contract violation test — the assertion's
#           full status-face promise: 200+{groups:[{id,hits}]} on valid,
#           400 on invalid group_by, 404 on missing collection
# endpoint: points+query+groups
# constraint_ids: qdrant_behavioral_points_query_groups_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points-groups
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 + BS-05 (grouping "requires payload values for the
#            group_by field" — a group_by with no payload values behind it
#            is the documented invalid input and must draw 400, not a silent
#            200 with empty groups; the response envelope must carry
#            result.groups[].id and .hits per the published response shape)
"""
TestVDB Semantic Attack Script
Target: qdrant v1.18.0
Attack: strategy1 behavioral_contract x
  qdrant_behavioral_points_query_groups_001 — legs, in order:
    V  valid: group_by on a populated payload field -> HTTP 200 with
       result.groups a non-empty list whose entries each carry 'id' and a
       non-empty 'hits' list (response_shape: result.groups[].id any,
       result.groups[].hits array)
    I1 invalid group_by: group_by="no_such_field_zz" (no payload values
       behind it anywhere in the collection) -> EXACTLY 400 per the
       assertion; a 200 (empty groups or otherwise) = Type1_IllegalSuccess
    I2 invalid group_by: group_by="" (empty field name) -> EXACTLY 400
    M  missing collection: same valid body against a never-created
       collection name -> EXACTLY 404 per the assertion; any other status
       (2xx or non-404 4xx) = the documented status face not honored
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
Oracle: V -> HTTP 200, result.groups non-empty list, every group has key
  'id' and a non-empty list under 'hits' (shape violation = Type4); I1 ->
  EXACTLY HTTP 400 (200 = Type1_IllegalSuccess DEFECT — invalid group_by
  accepted); I2 -> EXACTLY HTTP 400 (200 = Type1_IllegalSuccess); M ->
  EXACTLY HTTP 404 (2xx = Type1_IllegalSuccess; non-404 4xx =
  Type4_StateLogicViolation — documented status face not honored); 5xx with
  /healthz alive = Type3_RuntimeFailure; transport failure -> /healthz
  liveness re-check then SCRIPT_ERROR (constraint
  qdrant_behavioral_points_query_groups_001).
Constraint: qdrant_behavioral_points_query_groups_001 — "grouping requires
  payload values for the group_by field; returns 200 {groups: [{id,
  hits}]}; 400 on an invalid group_by; 404 for a missing collection"
  (evidence_tier: explicit; level: endpoint)

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


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "spqgV1" + tag
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

        def post(name, path, group_by):
            body = {"query": {"nearest": ANCHOR}, "group_by": group_by,
                    "params": {"exact": True}, "group_size": 2, "limit": 5}
            rs, rbody, rraw = safe_request("POST", path, json=body, timeout=60)
            print(f"[{name}] status={rs} raw: {rraw[:400]}")
            if rs == -1:
                bail_transport(name)
                return "BAIL"
            if handle_5xx(rs, rraw, name):
                return "STOP"
            return rs, groups_of(rbody), rraw

        # ---- V: valid group_by -> 200 + {groups:[{id,hits}]} ----
        out = post("V valid group_by=grp", qpath, "grp")
        if out in ("BAIL", "STOP"):
            return
        rs, groups, _ = out
        if not (200 <= rs <= 299):
            print(f"VERDICT: SCRIPT_ERROR — V valid leg status {rs}; fixture unusable")
            return
        if not groups:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — V: 200 but "
                  f"result.groups missing/not a list (published response shape "
                  f"promises groups:[{{id,hits}}])")
            return
        for g in groups:
            if not isinstance(g, dict) or "id" not in g or not isinstance(g.get("hits"), list) or not g["hits"]:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — V: group "
                      f"entry violates the promised shape {{id, hits}}: {str(g)[:200]}")
                return
        print(f"V: {len(groups)} groups, every entry carries id + non-empty hits")

        # ---- I1: group_by with no payload values -> 400 ----
        out = post("I1 group_by=no_such_field_zz", qpath, "no_such_field_zz")
        if out in ("BAIL", "STOP"):
            return
        rs, groups, _ = out
        if 200 <= rs <= 299:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — I1: group_by on a "
                  f"field with NO payload values returned {rs} (groups="
                  f"{str(groups)[:120]}); the assertion pins '400 on an invalid "
                  f"group_by' (grouping requires payload values for group_by)")
            return
        if rs != 400:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — I1: expected "
                  f"EXACTLY 400 for invalid group_by, got {rs}")
            return
        print("I1: invalid group_by rejected with 400 as documented")

        # ---- I2: empty-string group_by -> 400 ----
        out = post("I2 group_by=''", qpath, "")
        if out in ("BAIL", "STOP"):
            return
        rs, groups, _ = out
        if 200 <= rs <= 299:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — I2: empty-string "
                  f"group_by returned {rs} (groups={str(groups)[:120]}); the "
                  f"assertion pins '400 on an invalid group_by'")
            return
        if rs != 400:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — I2: expected "
                  f"EXACTLY 400 for empty group_by, got {rs}")
            return
        print("I2: empty group_by rejected with 400 as documented")

        # ---- M: missing collection -> 404 ----
        absent = "spqg_absent_" + tag
        out = post("M missing collection", f"/collections/{absent}/points/query/groups", "grp")
        if out in ("BAIL", "STOP"):
            return
        rs, _, _ = out
        if 200 <= rs <= 299:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — M: query against "
                  f"never-created collection '{absent}' returned {rs}; the "
                  f"assertion pins '404 for a missing collection'")
            return
        if rs != 404:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — M: expected "
                  f"EXACTLY 404 for a missing collection, got {rs} — documented "
                  f"status face not honored")
            return
        print("M: missing collection answered with 404 as documented")

        print("V/I1/I2/M all match the asserted status faces")
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
