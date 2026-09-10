#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_query_groups_offset_001
# strategy: state_consistency (offset-pollution probe on the groups face)
# endpoint: points+query+groups
# constraint_ids: qdrant_state_points_query_groups_001
# source_url: https://qdrant.tech/documentation/search/search/
# doc_version: current (site latest; no version archive)
"""
Attack: offset-pollution probe x qdrant_state_points_query_groups_001
  ("the groups query API does not allow offset (pagination); pagination
  is not available with groups"). Setup seeds a 4-group x 3-point
  partition (grp = g1..g4, keyword payload index per the R40
  index-precondition lesson), then runs the SAME deterministic groups
  query twice as a stability baseline (params.exact=true removes HNSW
  approximation nondeterminism), then sends the identical body with a
  top-level "offset": 2 injected. The spec-derived contract declares no
  offset parameter on this endpoint, so only two dispositions are legal:
  reject (4xx) or omit (200 identical to the offset-free baseline).
  Rationale for the mutation point (G6): offset is the one pagination
  knob the endpoint explicitly renounces; if serde silently forwards it
  into the underlying scroll/pagination machinery, groups get skipped
  while the client believes it received the full grouped result — a
  state-consistency (partial-result) violation invisible to status
  codes, which is exactly what a count-only oracle would miss.
  [chunk_points+query+groups coverage: state_consistency x
  qdrant_state_points_query_groups_001 (offset injected into groups
  body -> reject/omit are legal, silent skip = Type4)]
Oracle: offset request -> 4xx rejection OR 200 whose group-id/hit-id
  partition is byte-equivalent (as sets) to the offset-free baseline
  (both legal); 200 with a partition differing from a stable baseline =
  Type4_StateLogicViolation (undocumented pagination applied, e.g.
  baseline's first groups missing); 200 with result/groups malformed =
  Type4 result-completeness violation (R40 lesson); 5xx with /healthz
  alive = Type3_RuntimeFailure; post-probe exact count must remain 12
  and a repeat baseline query must reproduce the baseline partition
  (query must not mutate state) — mismatch = Type4.
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
      f"{[k for k in sorted(rt.PATHS) if k in ('query_groups', 'upsert_points', 'count', 'create_index', 'create_collection', 'drop_collection', 'healthz')]}")

DEFECTS = []
WARNINGS = []
ABORT = [False]

GROUPS = ["g1", "g2", "g3", "g4"]
POINT_MAP = {}
for _gi, _g in enumerate(GROUPS):
    POINT_MAP[_g] = [(_gi + 1) * 10 + j for j in (1, 2, 3)]  # g1:11,12,13 ... g4:41,42,43


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
    # deterministic distinct direction per point id (cosine-safe, no zero vector)
    return [float((pid % 7) + 1), float((pid % 5) + 1), float((pid % 3) + 1), float((pid % 2) + 1)]


def groups_body(extra=None):
    b = {"query": [1.0, 1.0, 1.0, 1.0], "group_by": "grp",
         "limit": 10, "group_size": 3, "params": {"exact": True}}
    if extra:
        b.update(extra)
    return b


def parse_partition(status, raw, tag):
    """Return partition dict {group_id: sorted hit ids} or None.

    None + status 200 = malformed-200 (result-completeness violation).
    None + non-200 = response not parseable for structural checks (caller
    handles disposition typing by status).
    """
    try:
        body = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        body = None
    if status == 200:
        if not isinstance(body, dict):
            DEFECTS.append(f"({tag}) 200 with non-JSON/unparseable body — "
                           f"result-completeness violation — Type4_StateLogicViolation — "
                           f"raw={str(raw)[:150]}")
            return None
        res = body.get("result")
        if not isinstance(res, dict) or not isinstance(res.get("groups"), list):
            DEFECTS.append(f"({tag}) 200 but result.groups missing or not an array — "
                           f"result-completeness violation (R40 lesson) — "
                           f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
            return None
        part = {}
        for g in res["groups"]:
            if not isinstance(g, dict) or "id" not in g or not isinstance(g.get("hits"), list):
                DEFECTS.append(f"({tag}) 200 but a group entry lacks id/hits — "
                               f"malformed-200 — Type4_StateLogicViolation — "
                               f"entry={str(g)[:120]}")
                return None
            part[str(g["id"])] = sorted(h.get("id") for h in g["hits"]
                                        if isinstance(h, dict))
        return part
    return None


def handle_transport(tag, status, raw):
    """Returns True if the run must stop (abort), False to continue."""
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
    PFX = "spqg1_" + TS + "_"
    C = PFX + "col"

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
            print(f"SETUP_ERROR: seed upsert returned {s_up}")
            return "SCRIPT_ERROR"

        # payload index precondition (R40 lesson: group_by needs the index first)
        s_ix, raw_ix = safe_request("PUT", "create_index",
                                    path_params={"name": C},
                                    body={"field_name": "grp",
                                          "field_schema": "keyword"},
                                    query_params={"wait": "true"})
        print(f"[index] status={s_ix} raw={str(raw_ix)[:160]}")
        if s_ix not in (200, 201):
            print(f"SETUP_ERROR: keyword index on grp returned {s_ix}")
            return "SCRIPT_ERROR"

        cnt0 = exact_count(C)
        print(f"[count0] {cnt0}")
        if cnt0 != 12:
            print(f"SETUP_ERROR: expected 12 seeded points, count={cnt0}")
            return "SCRIPT_ERROR"

        # ---- stability baseline: same deterministic query twice ----
        s1, r1 = safe_request("POST", "query_groups", path_params={"name": C},
                              body=groups_body())
        s2, r2 = safe_request("POST", "query_groups", path_params={"name": C},
                              body=groups_body())
        print(f"[baseline q1] status={s1} raw={str(r1)[:200]}")
        print(f"[baseline q2] status={s2}")
        if handle_transport("baseline", s1, r1) or handle_transport("baseline2", s2, r2):
            return verdict()
        if s1 not in (200,) or s2 not in (200,):
            print(f"SETUP_ERROR: baseline groups query returned {s1}/{s2}")
            return "SCRIPT_ERROR"

        p1 = parse_partition(s1, r1, "baseline-q1")
        p2 = parse_partition(s2, r2, "baseline-q2")
        if p1 is None or p2 is None:
            return verdict()
        stable = (p1 == p2)
        print(f"[baseline] partition={p1} stable={stable}")
        expected = {g: sorted(POINT_MAP[g]) for g in GROUPS}
        if p1 != expected:
            # baseline itself must be the exact partition before any attack claim
            print(f"SETUP_ERROR: baseline partition != seeded partition: {p1} vs {expected}")
            return "SCRIPT_ERROR"

        # ---- attack: same body + offset ----
        s_a, r_a = safe_request("POST", "query_groups", path_params={"name": C},
                                body=groups_body({"offset": 2}))
        print(f"[attack offset=2] status={s_a} raw={str(r_a)[:250]}")
        if handle_transport("attack-offset", s_a, r_a):
            return verdict()
        if 400 <= s_a <= 499:
            print(f"[attack] offset rejected with {s_a} — legal 'reject' disposition "
                  f"per qdrant_state_points_query_groups_001")
        elif s_a == 200:
            pa = parse_partition(s_a, r_a, "attack-offset")
            if pa is not None:
                if pa == p1:
                    print("[attack] 200 partition identical to baseline — legal "
                          "'omit' disposition (offset silently dropped, not applied)")
                else:
                    missing = [g for g in p1 if g not in pa]
                    skip_sig = (len(missing) >= 2 and
                                all(pa.get(g) == p1[g] for g in pa))
                    detail = (f"baseline groups {sorted(p1)} -> attack groups "
                              f"{sorted(pa)}; missing={missing}")
                    if stable:
                        DEFECTS.append(f"(attack-offset) offset=2 accepted with 200 "
                                       f"and CHANGED the grouped result — undocumented "
                                       f"pagination applied on the groups endpoint "
                                       f"(contract: pagination not available with "
                                       f"groups) — Type4_StateLogicViolation — {detail}")
                    elif skip_sig:
                        DEFECTS.append(f"(attack-offset) unstable baseline, but the "
                                       f"attack shows the skip signature of applied "
                                       f"offset (first groups dropped) — "
                                       f"Type4_StateLogicViolation — {detail}")
                    else:
                        WARNINGS.append(f"(attack-offset) partition differs from "
                                        f"baseline but baseline was unstable and no "
                                        f"clean skip signature — {detail}")
        elif s_a not in (200,):
            WARNINGS.append(f"(attack-offset) unexpected status {s_a} — raw={str(r_a)[:120]}")

        # ---- post-probe state: query must not have mutated anything ----
        cnt1 = exact_count(C)
        if isinstance(cnt1, int) and cnt1 != 12:
            DEFECTS.append(f"(post-probe) exact count {cnt1} != 12 after read-only "
                           f"groups probes — Type4_StateLogicViolation")
        else:
            print(f"[post-probe count] {cnt1}")
        s3, r3 = safe_request("POST", "query_groups", path_params={"name": C},
                              body=groups_body())
        print(f"[post-probe query] status={s3}")
        if not handle_transport("post-query", s3, r3) and s3 == 200:
            p3 = parse_partition(s3, r3, "post-query")
            if p3 is not None and p3 != p1 and stable:
                DEFECTS.append(f"(post-probe) repeat baseline query partition "
                               f"changed after offset probe {p1} -> {p3} — "
                               f"read mutated state — Type4_StateLogicViolation")

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
