#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_query_groups_missing404_004
# strategy: delete_consistency (post-DELETE invisibility on the groups face)
# endpoint: points+query+groups
# constraint_ids: qdrant_behavioral_points_query_groups_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points-groups
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: missing-collection disposition x
  qdrant_behavioral_points_query_groups_001 ("404 for a missing
  collection"), Strategy 2 (post-DELETE consistency) on the groups face.
  Leg A probes a never-existing collection name; leg B creates a
  collection, seeds a 4x3 partition, verifies a 200 groups response
  (precondition), drops the collection, then re-issues the identical
  groups query — the dropped collection must be invisible (404). A 200
  after the drop is a zombie read (Type4); a 5xx is an internal error
  (Type3, reference qdrant #9229 family). Cross-face leg (G9): the plain
  query face (points+query) is probed on the same missing names — if the
  two faces of the same collection-name parameter family disagree within
  4xx (e.g. query->404 but query/groups->400), that asymmetry is printed
  as a defect signal alongside the assertion's explicit 404 wording.
  [chunk_points+query+groups coverage: delete_consistency x
  qdrant_behavioral_points_query_groups_001 (never-existing -> 404;
  post-drop -> 404; zombie 200 = Type4; cross-face 4xx asymmetry signal)]
Oracle: groups query on never-existing name -> 404; after
  DELETE collection the identical groups query -> 404 (200 = Type4
  zombie read, any other non-404 4xx = disposition violation of the
  explicit 404 promise + G9 cross-face asymmetry vs the points+query
  face probed in the same run); 5xx with /healthz alive =
  Type3_RuntimeFailure; pre-drop control query must be 200 with a
  well-formed result.groups array (malformed 200 = Type4).
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
      f"{[k for k in sorted(rt.PATHS) if k in ('query_groups', 'query', 'upsert_points', 'create_index', 'drop_collection', 'healthz')]}")

DEFECTS = []
WARNINGS = []
ABORT = [False]


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


def groups_body():
    return {"query": [1.0, 1.0, 1.0, 1.0], "group_by": "grp",
            "limit": 10, "group_size": 3, "params": {"exact": True}}


def check_missing_face(coll, tag):
    """Groups query against a (supposedly) missing collection; returns status."""
    s, raw = safe_request("POST", "query_groups", path_params={"name": coll},
                          body=groups_body())
    print(f"[{tag} groups-face] status={s} raw={str(raw)[:220]}")
    if handle_transport(tag, s, raw):
        return None
    if s == 200:
        try:
            res = json.loads(raw).get("result")
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
            res = None
        if not isinstance(res, dict) or not isinstance(res.get("groups"), list):
            DEFECTS.append(f"({tag}) 200 against a missing collection AND "
                           f"malformed body — Type4_StateLogicViolation — "
                           f"raw={str(raw)[:150]}")
        else:
            DEFECTS.append(f"({tag}) groups query returned 200 against a "
                           f"missing collection (zombie read) — assertion "
                           f"declares 404 — Type4_StateLogicViolation")
    elif s == 404:
        print(f"[{tag}] OK: 404 as declared")
    elif 400 <= s <= 499:
        DEFECTS.append(f"({tag}) groups face returned {s} instead of the "
                       f"declared 404 for a missing collection — disposition "
                       f"violation of qdrant_behavioral_points_query_groups_001 "
                       f"(Type4) — raw={str(raw)[:150]}")
    return s


def cross_face_query(coll, tag):
    s, raw = safe_request("POST", "query", path_params={"name": coll},
                          body={"query": [1.0, 1.0, 1.0, 1.0], "limit": 3})
    print(f"[{tag} query-face] status={s} raw={str(raw)[:150]}")
    handle_transport(tag + "-queryface", s, raw)
    return s


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spqg4_" + TS + "_"
    C = PFX + "col"
    NEVER = PFX + "never_exists"

    try:
        # ---- leg A: never-existing collection ----
        s_g = check_missing_face(NEVER, "never-existing")
        if ABORT[0]:
            return verdict()
        s_q = cross_face_query(NEVER, "never-existing")
        if isinstance(s_g, int) and isinstance(s_q, int) and \
                400 <= s_g <= 499 and 400 <= s_q <= 499 and s_g != s_q:
            print(f"SIGNAL G9: same missing-name family disposed differently "
                  f"across faces: query={s_q} vs query/groups={s_g}")

        # ---- leg B: create -> verify 200 control -> drop -> 404 ----
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        pts = [{"id": (gi + 1) * 10 + j,
                "vector": [float(((gi + 1) * 10 + j) % 7 + 1), 1.0, 0.5, 0.25],
                "payload": {"grp": g}}
               for gi, g in enumerate(["g1", "g2", "g3", "g4"])
               for j in (1, 2, 3)]
        s_up, raw_up = safe_request("PUT", "upsert_points",
                                    path_params={"name": C},
                                    body={"points": pts},
                                    query_params={"wait": "true"})
        print(f"[seed] status={s_up}")
        if s_up not in (200, 201):
            return "SCRIPT_ERROR"
        s_ix, _ = safe_request("PUT", "create_index", path_params={"name": C},
                               body={"field_name": "grp", "field_schema": "keyword"},
                               query_params={"wait": "true"})
        if s_ix not in (200, 201):
            return "SCRIPT_ERROR"

        s_ctl, r_ctl = safe_request("POST", "query_groups", path_params={"name": C},
                                    body=groups_body())
        print(f"[control pre-drop] status={s_ctl} raw={str(r_ctl)[:200]}")
        if handle_transport("control", s_ctl, r_ctl):
            return verdict()
        if s_ctl != 200:
            print(f"SETUP_ERROR: control groups query returned {s_ctl}")
            return "SCRIPT_ERROR"
        try:
            res = json.loads(r_ctl).get("result")
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
            res = None
        if not isinstance(res, dict) or not isinstance(res.get("groups"), list):
            DEFECTS.append("(control) 200 but result.groups missing/not array — "
                           "malformed-200 — Type4_StateLogicViolation — "
                           f"raw={str(r_ctl)[:150]}")

        # drop (idempotent semantics; wait not applicable to DELETE collection)
        s_del, r_del = safe_request("DELETE", "drop_collection",
                                    path_params={"name": C})
        print(f"[drop] status={s_del} raw={str(r_del)[:160]}")
        if s_del not in (200, 201, 404):
            handle_transport("drop", s_del, r_del)
            print(f"SETUP_ERROR: drop returned {s_del}")
            return "SCRIPT_ERROR"

        s_g2 = check_missing_face(C, "post-drop")
        if ABORT[0]:
            return verdict()
        s_q2 = cross_face_query(C, "post-drop")
        if isinstance(s_g2, int) and isinstance(s_q2, int) and \
                400 <= s_g2 <= 499 and 400 <= s_q2 <= 499 and s_g2 != s_q2:
            print(f"SIGNAL G9: post-drop disposition differs across faces: "
                  f"query={s_q2} vs query/groups={s_g2}")

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
