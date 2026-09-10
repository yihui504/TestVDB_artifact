#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_query_groups_floor_002
# strategy: count_consistency (boundary closure + post-rejection state check)
# endpoint: points+query+groups
# constraint_ids: qdrant_range_points_query_groups_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points-groups
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: group_size/limit floor closure + post-rejection state consistency
  x qdrant_range_points_query_groups_001 ("group_size minimum 1 (default
  3); limit minimum 1 (default 10)"). G4 positive-negative pairing on the
  declared floor: the positive leg exercises the closure (group_size=1,
  limit=1 — the minimums themselves MUST be accepted) and the defaults
  (both omitted -> <=3 hits/group, <=10 groups); the negative leg sends
  group_size=0 and limit=0 (one dimension below the floor) which MUST be
  rejected 4xx. The state leg then re-verifies the exact 4x3 partition
  and exact count after every rejected probe — a floor violation that is
  accepted (200) is a Type1_IllegalSuccess against the explicit minimum,
  and any probe that leaves the partition/count changed is a
  Type4_StateLogicViolation (rejected writes must not touch state).
  params.exact=true keeps every query deterministic (HNSW approximation
  nondeterminism is by-design per the threat model and is excluded).
  [chunk_points+query+groups coverage: boundary-closure x
  qdrant_range_points_query_groups_001 (group_size/limit min-1 closure +
  below-floor rejection + state-unchanged verification)]
Oracle: group_size=1&limit=1 -> 200 with exactly 1 group and <=1 hit
  (violation = Type4 shape); defaults omitted -> 200, 4 groups x 3 hits
  exact partition (mismatch = Type4); group_size=0 -> 4xx and limit=0 ->
  4xx (200 on either = Type1_IllegalSuccess vs explicit min-1); malformed
  200 (result.groups missing/not array) = Type4; 5xx with /healthz alive
  = Type3_RuntimeFailure; after all probes exact count == 12 and the
  baseline partition reproduces — drift = Type4.
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
             for gi, g in enumerate(GROUPS)}  # g1:11,12,13 ... g4:41,42,43


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


def parse_groups_or_defect(status, raw, tag):
    """200-only structural parse. Returns list of group dicts or None (defect recorded)."""
    try:
        body = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        body = None
    if not isinstance(body, dict):
        DEFECTS.append(f"({tag}) 200 with unparseable body — malformed-200 — "
                       f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
        return None
    res = body.get("result")
    if not isinstance(res, dict) or not isinstance(res.get("groups"), list):
        DEFECTS.append(f"({tag}) 200 but result.groups missing or not an array — "
                       f"result-completeness violation (R40 lesson) — "
                       f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
        return None
    for g in res["groups"]:
        if not isinstance(g, dict) or "id" not in g or not isinstance(g.get("hits"), list):
            DEFECTS.append(f"({tag}) group entry lacks id/hits — malformed-200 — "
                           f"Type4_StateLogicViolation — entry={str(g)[:120]}")
            return None
    return res["groups"]


def partition_of(groups):
    return {str(g["id"]): sorted(h.get("id") for h in g["hits"] if isinstance(h, dict))
            for g in groups}


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


def qgroups(coll, body, tag):
    s, raw = safe_request("POST", "query_groups", path_params={"name": coll}, body=body)
    print(f"[{tag}] status={s} raw={str(raw)[:220]}")
    handle_transport(tag, s, raw)
    return s, raw


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
    C = "spqg2_" + TS + "_col"
    BASE_Q = {"query": [1.0, 1.0, 1.0, 1.0], "group_by": "grp",
              "params": {"exact": True}}
    EXPECTED = {g: sorted(POINT_MAP[g]) for g in GROUPS}

    try:
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        pts = [{"id": pid, "vector": vec_for(pid), "payload": {"grp": g}}
               for g, ids in POINT_MAP.items() for pid in ids]
        s_up, raw_up = safe_request("PUT", "upsert_points",
                                    path_params={"name": C},
                                    body={"points": pts},
                                    query_params={"wait": "true"})
        print(f"[seed] status={s_up} raw={str(raw_up)[:160]}")
        if s_up not in (200, 201):
            return "SCRIPT_ERROR"
        s_ix, raw_ix = safe_request("PUT", "create_index",
                                    path_params={"name": C},
                                    body={"field_name": "grp", "field_schema": "keyword"},
                                    query_params={"wait": "true"})
        print(f"[index] status={s_ix}")
        if s_ix not in (200, 201):
            return "SCRIPT_ERROR"

        # ---- positive leg 1: defaults omitted (group_size=3 / limit=10 defaults) ----
        s, raw = qgroups(C, dict(BASE_Q), "defaults-omitted")
        if s == 200:
            gs = parse_groups_or_defect(s, raw, "defaults-omitted")
            if gs is not None:
                part = partition_of(gs)
                if part != EXPECTED:
                    DEFECTS.append(f"(defaults-omitted) partition {part} != seeded "
                                   f"4x3 partition {EXPECTED} with default "
                                   f"group_size=3/limit=10 covering all groups — "
                                   f"Type4_StateLogicViolation")
                else:
                    print("[defaults-omitted] OK: exact 4x3 partition")
        elif ABORT[0]:
            return verdict()

        # ---- positive leg 2: floor closure group_size=1, limit=1 ----
        s, raw = qgroups(C, dict(BASE_Q, group_size=1, limit=1), "floor-closure-1-1")
        if s == 200:
            gs = parse_groups_or_defect(s, raw, "floor-closure-1-1")
            if gs is not None:
                if len(gs) != 1:
                    DEFECTS.append(f"(floor-closure) limit=1 returned {len(gs)} "
                                   f"groups (min-1 closure must be accepted and "
                                   f"honored) — Type4_StateLogicViolation")
                for g in gs:
                    if len(g["hits"]) > 1:
                        DEFECTS.append(f"(floor-closure) group_size=1 returned "
                                       f"{len(g['hits'])} hits in group {g.get('id')} "
                                       f"— cap not honored — Type4_StateLogicViolation")
                if len(gs) == 1 and len(gs[0]["hits"]) <= 1:
                    print("[floor-closure] OK: 1 group, <=1 hit")
        elif ABORT[0]:
            return verdict()

        # ---- negative leg: below-floor values must be rejected ----
        for field in ("group_size", "limit"):
            s, raw = qgroups(C, dict(BASE_Q, **{field: 0}), f"{field}-zero")
            if ABORT[0]:
                return verdict()
            if s == 200:
                gs = parse_groups_or_defect(s, raw, f"{field}-zero")
                DEFECTS.append(f"({field}-zero) {field}=0 accepted with 200 — "
                               f"violates explicit minimum 1 (qdrant_range_points_"
                               f"query_groups_001) — Type1_IllegalSuccess — "
                               f"raw={str(raw)[:150]}")
            elif 400 <= s <= 499:
                print(f"[{field}-zero] OK: rejected with {s}")
            elif s not in (0,) and not (500 <= s <= 599):
                WARNINGS.append(f"({field}-zero) unexpected status {s} — "
                                f"raw={str(raw)[:120]}")

        # ---- state leg: rejected probes must not have touched state ----
        cnt = exact_count(C)
        if isinstance(cnt, int) and cnt != 12:
            DEFECTS.append(f"(state) exact count {cnt} != 12 after floor probes — "
                           f"Type4_StateLogicViolation")
        else:
            print(f"[state] count={cnt}")
        s, raw = qgroups(C, dict(BASE_Q, group_size=3, limit=10), "post-floor-baseline")
        if s == 200:
            gs = parse_groups_or_defect(s, raw, "post-floor-baseline")
            if gs is not None:
                part = partition_of(gs)
                if part != EXPECTED:
                    DEFECTS.append(f"(state) post-probe partition {part} != baseline "
                                   f"{EXPECTED} — rejected floor probes changed state — "
                                   f"Type4_StateLogicViolation")

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
