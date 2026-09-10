#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_query_groups_payload_003
# strategy: state_consistency (group_by payload-domain partition)
# endpoint: points+query+groups
# constraint_ids: qdrant_behavioral_points_query_groups_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points-groups
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: group_by payload-domain partition x
  qdrant_behavioral_points_query_groups_001 ("grouping requires payload
  values for the group_by field; returns 200 {groups: [{id, hits}]}; 400
  on an invalid group_by"). Setup seeds 12 points carrying grp=g1..g4
  (4x3) PLUS 4 points (ids 901-904) that deliberately LACK the grp
  payload field. Positive leg: with the keyword payload index in place
  (index precondition, R40 lesson) the groups query must return the exact
  4x3 partition AND the payload-less points must contribute to no group —
  a point without a group_by value surfacing inside any group is a
  state-consistency violation. Negative leg: group_by on a field that
  exists nowhere ("no_such_field_xyz") must be 400 per the assertion's
  explicit wording. Observation leg (before index creation): the no-index
  disposition is recorded but NOT adjudicated — the contract does not
  declare an index requirement, so 200 (works without index) and 400
  (vendor precondition, ORDER_BY-precondition analog from R40) are both
  legal; only 5xx / malformed-200 are defects there.
  [chunk_points+query+groups coverage: state_consistency x
  qdrant_behavioral_points_query_groups_001 (payload-domain partition +
  payload-less exclusion + invalid group_by -> 400)]
Oracle: valid groups query -> 200 with result.groups == [{id,hits}...]
  forming the exact seeded partition {g1..g4} and hit-id sets disjoint
  from {901..904} (payload-less point in a group, or a group id outside
  the written domain = Type4_StateLogicViolation); group_by on a
  nonexistent field -> 400 (200 = Type1_IllegalSuccess vs the assertion's
  explicit "400 on an invalid group_by"); no-index leg -> 200-well-formed
  or 400 both pass, 5xx with /healthz alive = Type3, malformed 200 =
  Type4; final exact count == 16 (read-only session).
"""

import os
import sys
import json
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---- bootstrap (three-layer fallback: env -> upward walk -> contract target) ----
_sd = os.environ.get("TESTVDB_SCRIPTS_DIR")
if not _sd:
    for _p in Path(__file__).resolve().parents:
        if (_p / "scripts" / "runtime" / "__init__.py").exists():
            _sd = str(_p / "scripts")
            break
if not _sd or not Path(_sd, "runtime", "__init__.py").exists():
    print("VERDICT: SCRIPT_ERROR - runtime scripts dir not found (TESTVDB_SCRIPTS_DIR unset)")
    sys.exit(2)
sys.path.insert(0, _sd)

if not os.environ.get("TESTVDB_TARGET"):
    for _p in Path(__file__).resolve().parents:
        _c = _p / "structured_contract.json"
        if _c.exists():
            try:
                _t = json.loads(_c.read_text(encoding="utf-8")).get("target", "")
                if _t:
                    os.environ["TESTVDB_TARGET"] = str(_t).lower()
            except Exception:
                pass
            break

try:
    from runtime import get_runtime
    rt = get_runtime()
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR - runtime import failed: {e}")
    sys.exit(2)

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)

print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if k in ('query_groups', 'upsert_points', 'count', 'create_index', 'drop_collection', 'healthz')]}")

DEFECTS = []
WARNINGS = []
ABORT = [False]

GROUPS = ["g1", "g2", "g3", "g4"]
POINT_MAP = {g: [(gi + 1) * 10 + j for j in (1, 2, 3)]
             for gi, g in enumerate(GROUPS)}          # 12 grouped points
NO_GRP_IDS = [901, 902, 903, 904]                     # payload-less points


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
    print(f"[liveness {tag}] healthz probe required")
    _hs, _hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={_hs} raw={str(_hraw)[:120]}")
    return _hs == 200


def vec_for(pid):
    return [float((pid % 7) + 1), float((pid % 5) + 1), float((pid % 3) + 1), float((pid % 2) + 1)]


def handle_transport(tag, status, raw):
    if status == 0:
        if not liveness(tag):
            ABORT[0] = True
            return True
        WARNINGS.append(f"({tag}) transport failure {str(raw)[:100]} but /healthz alive")
        return False
    if 500 <= status <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) returned {status} with service alive — "
                           f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
        else:
            ABORT[0] = True
            return True
    return False


def parse_groups_or_defect(status, raw, tag):
    try:
        body = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        body = None
    if not isinstance(body, dict):
        DEFECTS.append(f"({tag}) {status} with unparseable body — "
                       f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
        return None
    res = body.get("result")
    if not isinstance(res, dict) or not isinstance(res.get("groups"), list):
        if status == 200:
            DEFECTS.append(f"({tag}) 200 but result.groups missing or not an array — "
                           f"result-completeness violation (R40 lesson) — "
                           f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
            return None
        return []  # error body on non-200 — disposition typed by caller
    for g in res["groups"]:
        if not isinstance(g, dict) or "id" not in g or not isinstance(g.get("hits"), list):
            DEFECTS.append(f"({tag}) group entry lacks id/hits — malformed response — "
                           f"Type4_StateLogicViolation — entry={str(g)[:120]}")
            return None
    return res["groups"]


def exact_count(coll):
    s, raw = safe_request("POST", "count", path_params={"name": coll},
                          body={"exact": True})
    if s == 200:
        try:
            return json.loads(raw).get("result", {}).get("count")
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
            return None
    handle_transport("count", s, raw)
    return None


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    C = "spqg3_" + TS + "_col"
    EXPECTED = {g: sorted(POINT_MAP[g]) for g in GROUPS}
    Q_BODY = {"query": [1.0, 1.0, 1.0, 1.0], "group_by": "grp",
              "limit": 10, "group_size": 3, "params": {"exact": True}}

    try:
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        pts = [{"id": pid, "vector": vec_for(pid), "payload": {"grp": g}}
               for g, ids in POINT_MAP.items() for pid in ids]
        pts += [{"id": pid, "vector": vec_for(pid)} for pid in NO_GRP_IDS]
        s_up, raw_up = safe_request("PUT", "upsert_points",
                                    path_params={"name": C},
                                    body={"points": pts},
                                    query_params={"wait": "true"})
        print(f"[seed 16] status={s_up} raw={str(raw_up)[:160]}")
        if s_up not in (200, 201):
            return "SCRIPT_ERROR"

        # ---- observation leg: groups query BEFORE any payload index ----
        s0, r0 = safe_request("POST", "query_groups", path_params={"name": C},
                              body=Q_BODY)
        print(f"[no-index observation] status={s0} raw={str(r0)[:220]}")
        if handle_transport("no-index", s0, r0):
            return verdict()
        if s0 == 200:
            parse_groups_or_defect(s0, r0, "no-index")
            print("[no-index observation] 200 — grouping works without index "
                  "(legal: contract declares no index requirement)")
        elif 400 <= s0 <= 499:
            print("[no-index observation] 4xx — vendor index precondition "
                  "(legal disposition, ORDER_BY-precondition analog; index is "
                  "created below before the adjudicated faces)")

        # ---- index precondition for the adjudicated legs ----
        s_ix, raw_ix = safe_request("PUT", "create_index",
                                    path_params={"name": C},
                                    body={"field_name": "grp", "field_schema": "keyword"},
                                    query_params={"wait": "true"})
        print(f"[index] status={s_ix}")
        if s_ix not in (200, 201):
            return "SCRIPT_ERROR"

        # ---- positive leg: exact partition + payload-less exclusion ----
        s1, r1 = safe_request("POST", "query_groups", path_params={"name": C},
                              body=Q_BODY)
        print(f"[positive] status={s1} raw={str(r1)[:260]}")
        if handle_transport("positive", s1, r1):
            return verdict()
        if s1 == 200:
            gs = parse_groups_or_defect(s1, r1, "positive")
            if gs is not None:
                part = {str(g["id"]): sorted(h.get("id") for h in g["hits"]
                                             if isinstance(h, dict)) for g in gs}
                foreign_groups = [gid for gid in part if gid not in EXPECTED]
                if foreign_groups:
                    DEFECTS.append(f"(positive) group ids outside the written "
                                   f"payload domain: {foreign_groups} — "
                                   f"Type4_StateLogicViolation")
                leaks = {gid: [i for i in ids if i in NO_GRP_IDS]
                         for gid, ids in part.items()}
                leaks = {k: v for k, v in leaks.items() if v}
                if leaks:
                    DEFECTS.append(f"(positive) payload-less points {leaks} "
                                   f"surfaced inside groups — grouping requires "
                                   f"payload values — Type4_StateLogicViolation")
                for gid in EXPECTED:
                    got = part.get(gid)
                    if got != EXPECTED[gid]:
                        DEFECTS.append(f"(positive) group {gid} hits {got} != "
                                       f"seeded {EXPECTED[gid]} — partition "
                                       f"inconsistent — Type4_StateLogicViolation")
                if not DEFECTS:
                    print("[positive] OK: exact 4x3 partition, payload-less "
                          "points excluded from every group")

        # ---- negative leg: invalid group_by (field exists nowhere) ----
        s2, r2 = safe_request("POST", "query_groups", path_params={"name": C},
                              body=dict(Q_BODY, group_by="no_such_field_xyz"))
        print(f"[invalid group_by] status={s2} raw={str(r2)[:220]}")
        if handle_transport("invalid-groupby", s2, r2):
            return verdict()
        if s2 == 200:
            gs = parse_groups_or_defect(s2, r2, "invalid-groupby")
            DEFECTS.append(f"(invalid group_by) group_by=no_such_field_xyz "
                           f"accepted with 200 — assertion declares 400 on an "
                           f"invalid group_by — Type1_IllegalSuccess — "
                           f"raw={str(r2)[:150]}")
        elif s2 in (400, 422):
            print(f"[invalid group_by] OK: rejected with {s2}")
        elif 400 <= s2 <= 499:
            WARNINGS.append(f"(invalid group_by) status {s2} (assertion "
                            f"declares 400) — raw={str(r2)[:120]}")

        # ---- read-only session check ----
        cnt = exact_count(C)
        if isinstance(cnt, int) and cnt != 16:
            DEFECTS.append(f"(read-only) exact count {cnt} != 16 after "
                           f"groups probes — read mutated state — "
                           f"Type4_StateLogicViolation")
        else:
            print(f"[read-only] count={cnt}")

        return verdict()
    finally:
        try:
            rt.drop_collection(C)
        except Exception:
            pass


def verdict():
    for w in WARNINGS:
        print(f"WARN: {w}")
    if DEFECTS:
        for d in DEFECTS:
            print(f"DEFECT: {d}")
        return "DEFECT_FOUND"
    if ABORT[0]:
        print("ABORT: environment/transport unavailable mid-run")
        return "SCRIPT_ERROR"
    return "NO_DEFECT"


if __name__ == "__main__":
    try:
        _v = main()
    except Exception:
        import traceback
        traceback.print_exc()
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
