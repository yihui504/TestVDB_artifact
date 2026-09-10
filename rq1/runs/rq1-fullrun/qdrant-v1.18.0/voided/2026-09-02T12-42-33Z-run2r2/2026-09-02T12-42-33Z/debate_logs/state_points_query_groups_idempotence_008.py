#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_query_groups_idempotence_008
# strategy: upsert_idempotence (read face = groups partition)
# endpoint: points+query+groups
# constraint_ids: qdrant_behavioral_points_query_groups_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points-groups
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: upsert idempotence observed through the groups partition x
  qdrant_behavioral_points_query_groups_001 (200 {groups:[{id,hits}]}).
  Strategy 3 with the groups face as the read-back oracle: seed a 4x3
  partition, capture partition P1, re-upsert the IDENTICAL 12 points
  (same ids, same vectors, same group payloads, wait=true) — idempotent
  upsert by id must leave count == 12 (24 = duplicated points) and the
  partition unchanged (P2 == P1 as sets); a duplicated point surfacing
  TWICE inside one group's hits is a double-count (Type4). Mutation leg:
  re-upsert ids 11,12,13 with grp moved g1->g2 — grouping must track the
  payload mutation exactly: g1 disappears (no members left), g2 grows to
  6 hits; a stale g1 group still holding the moved ids means the grouped
  read face is serving pre-mutation state (Type4). Count must remain 12
  throughout. params.exact=true keeps reads deterministic.
  [chunk_points+query+groups coverage: upsert_idempotence x
  qdrant_behavioral_points_query_groups_001 (identical re-upsert ->
  count/partition stable; payload move -> partition tracks mutation)]
Oracle: after identical re-upsert: exact count == 12 (mismatch =
  Type4_StateLogicViolation) and groups partition identical to baseline
  P1 (set-compare; mismatch or duplicate id within one group's hits =
  Type4); after moving ids 11,12,13 to g2: count still 12, groups ==
  {g2: 6 ids, g3: 3, g4: 3} with g1 absent or empty (g1 still holding
  moved ids = stale grouped state, Type4); 5xx with /healthz alive =
  Type3_RuntimeFailure; malformed 200 = Type4.
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


def vec_for(pid):
    return [float((pid % 7) + 1), float((pid % 5) + 1), float((pid % 3) + 1), float((pid % 2) + 1)]


def make_points():
    return [{"id": pid, "vector": vec_for(pid), "payload": {"grp": g}}
            for g, ids in POINT_MAP.items() for pid in ids]


def upsert(coll, pts, tag):
    s, raw = safe_request("PUT", "upsert_points", path_params={"name": coll},
                          body={"points": pts}, query_params={"wait": "true"})
    print(f"[{tag}] status={s} raw={str(raw)[:160]}")
    return s


def qgroups_partition(coll, tag, group_size=6):
    s, raw = safe_request("POST", "query_groups", path_params={"name": coll},
                          body={"query": [1.0, 1.0, 1.0, 1.0], "group_by": "grp",
                                "limit": 10, "group_size": group_size,
                                "params": {"exact": True}})
    print(f"[{tag}] status={s} raw={str(raw)[:260]}")
    if handle_transport(tag, s, raw):
        return None, s
    if s != 200:
        return None, s
    try:
        body = json.loads(raw)
    except (json.JSONDecodeError, ValueError, TypeError):
        body = None
    res = body.get("result") if isinstance(body, dict) else None
    if not isinstance(res, dict) or not isinstance(res.get("groups"), list):
        DEFECTS.append(f"({tag}) 200 but result.groups missing/not array — "
                       f"result-completeness violation (R40 lesson) — "
                       f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
        return None, s
    part = {}
    for g in res["groups"]:
        if not isinstance(g, dict) or "id" not in g or not isinstance(g.get("hits"), list):
            DEFECTS.append(f"({tag}) group entry lacks id/hits — malformed-200 — "
                           f"Type4_StateLogicViolation — entry={str(g)[:120]}")
            return None, s
        ids = [h.get("id") for h in g["hits"] if isinstance(h, dict)]
        if len(ids) != len(set(map(str, ids))):
            DEFECTS.append(f"({tag}) group {g.get('id')} has duplicate hit ids "
                           f"{ids} — double-counted point — "
                           f"Type4_StateLogicViolation")
        part[str(g["id"])] = sorted(ids)
    return part, s


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


def check_count(coll, expected, tag):
    cnt = exact_count(coll)
    print(f"[{tag} count] {cnt} (expected {expected})")
    if isinstance(cnt, int) and cnt != expected:
        DEFECTS.append(f"({tag}) exact count {cnt} != {expected} — "
                       f"Type4_StateLogicViolation")
    return cnt


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    C = "spqg8_" + TS + "_col"
    P1_EXPECTED = {g: sorted(POINT_MAP[g]) for g in GROUPS}

    try:
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        if upsert(C, make_points(), "seed") not in (200, 201):
            return "SCRIPT_ERROR"
        s_ix, _ = safe_request("PUT", "create_index", path_params={"name": C},
                               body={"field_name": "grp", "field_schema": "keyword"},
                               query_params={"wait": "true"})
        if s_ix not in (200, 201):
            return "SCRIPT_ERROR"
        check_count(C, 12, "seed")

        # ---- baseline partition ----
        p1, s1 = qgroups_partition(C, "baseline", group_size=3)
        if p1 is None:
            return verdict()
        if p1 != P1_EXPECTED:
            print(f"SETUP_ERROR: baseline partition {p1} != seeded {P1_EXPECTED}")
            return "SCRIPT_ERROR"

        # ---- idempotent re-upsert of the identical batch ----
        if upsert(C, make_points(), "identical-reupsert") not in (200, 201):
            return verdict()
        check_count(C, 12, "after-identical-reupsert")
        p2, _ = qgroups_partition(C, "after-reupsert", group_size=3)
        if p2 is not None and p2 != p1:
            DEFECTS.append(f"(idempotence) identical re-upsert changed the groups "
                           f"partition {p1} -> {p2} — upsert by id must be "
                           f"idempotent — Type4_StateLogicViolation")
        elif p2 is not None:
            print("[idempotence] OK: partition and count stable after "
                  "identical re-upsert")

        # ---- mutation leg: move ids 11,12,13 from g1 to g2 ----
        moved = [{"id": pid, "vector": vec_for(pid), "payload": {"grp": "g2"}}
                 for pid in POINT_MAP["g1"]]
        if upsert(C, moved, "move-g1-to-g2") not in (200, 201):
            return verdict()
        check_count(C, 12, "after-move")
        p3, _ = qgroups_partition(C, "after-move", group_size=6)
        if p3 is not None:
            expected3 = {"g2": sorted(POINT_MAP["g1"] + POINT_MAP["g2"]),
                         "g3": sorted(POINT_MAP["g3"]),
                         "g4": sorted(POINT_MAP["g4"])}
            stale_g1 = p3.get("g1")
            if stale_g1:
                DEFECTS.append(f"(mutation) group g1 still holds {stale_g1} after "
                               f"all its points were re-upserted to g2 — stale "
                               f"grouped state — Type4_StateLogicViolation")
            for gid in expected3:
                if p3.get(gid) != expected3[gid]:
                    DEFECTS.append(f"(mutation) group {gid} hits {p3.get(gid)} != "
                                   f"expected {expected3[gid]} — grouping did not "
                                   f"track the payload mutation — "
                                   f"Type4_StateLogicViolation")
            if not any("mutation" in d for d in DEFECTS):
                print("[mutation] OK: g1 gone, g2 == 6 merged ids, partition "
                      "tracks payload mutation")

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
