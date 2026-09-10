#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_query_groups_concurrent_006
# strategy: concurrent (BS-03 Concurrency State Blindness)
# endpoint: points+query+groups
# constraint_ids: qdrant_behavioral_points_query_groups_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points-groups
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: concurrent group-value writes x interleaved grouped reads x
  qdrant_behavioral_points_query_groups_001 (200 {groups:[{id,hits}]});
  Blindspot: BS-03 Concurrency State Blindness. T writer threads
  (TESTVDB_CONCURRENT_THREADS, clamped 2..10) each own a DISTINCT new
  group value conc_0..conc_{T-1} and upsert 3 points (wait=false — the
  async path is where partial-commit races live) while the main thread
  hammers groups queries. In-flight oracles (per 200 response, malformed
  200 = Type4 result-completeness): every group id must belong to the
  KNOWN domain {g1..g4} x {conc_t} — a group id that was never written
  is a fabricated group (Type4); len(groups) <= limit; hits <=
  group_size; no duplicate point id inside one group's hits (double-read
  of a partially committed point). Monotonic visibility is NOT asserted
  (eventual consistency is legal). Final leg (after join + eventual-
  consistency settle): exact count == 12 + 3T and the groups query must
  return the complete 4+T partition with each conc_t group holding
  exactly its 3 ids — lost or duplicated writes surface here as Type4.
  [chunk_points+query+groups coverage: concurrent x
  qdrant_behavioral_points_query_groups_001 (writer threads adding new
  group values vs interleaved grouped reads: domain purity, caps,
  in-group duplicates, final partition + count)]
Oracle: every in-flight 200 response well-formed with group ids within
  the written domain, <= limit groups, <= group_size hits per group and
  no duplicate ids within a group (violations = Type4); in-flight 5xx
  with /healthz alive = Type3_RuntimeFailure; after all writers join +
  settle: exact count == 12 + 3T (mismatch = Type4) and groups query
  returns exactly {g1..g4, conc_0..conc_{T-1}} with each group's hit-id
  set equal to its seeded/written ids (mismatch = Type4).
"""

import os
import sys
import json
import time
import threading
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

BASE_GROUPS = ["g1", "g2", "g3", "g4"]
POINT_MAP = {g: [(gi + 1) * 10 + j for j in (1, 2, 3)]
             for gi, g in enumerate(BASE_GROUPS)}
PER_THREAD = 3

try:
    T = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "20"))
except ValueError:
    T = 20
T = max(2, min(T, 20))
CONC_GROUPS = [f"conc_{t}" for t in range(T)]
KNOWN = set(BASE_GROUPS) | set(CONC_GROUPS)
LIMIT = 4 + T + 2


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


def writer_thread(coll, t, tally):
    g = CONC_GROUPS[t]
    pts = [{"id": 1000 + t * 10 + j, "vector": vec_for(1000 + t * 10 + j),
            "payload": {"grp": g}} for j in range(1, PER_THREAD + 1)]
    for attempt in range(3):  # one retry on transient failure; final must stick
        s, raw = safe_request("PUT", "upsert_points", path_params={"name": coll},
                              body={"points": pts})  # wait=false: async race window
        tally[f"upsert_{s}"] = tally.get(f"upsert_{s}", 0) + 1
        if s in (200, 201):
            return
        if s == 0 or 500 <= s <= 599:
            if not handle_transport(f"writer-{t}", s, raw):
                continue
            return
        time.sleep(0.2)
    DEFECTS.append(f"(writer-{t}) upsert of conc group failed after retries — "
                   f"last raw={str(raw)[:120]}")


def check_inflight_groups(raw, tag):
    """Structural/domain checks on one in-flight 200 response."""
    try:
        body = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        body = None
    if not isinstance(body, dict):
        DEFECTS.append(f"({tag}) 200 with unparseable body — malformed-200 — "
                       f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
        return
    res = body.get("result")
    if not isinstance(res, dict) or not isinstance(res.get("groups"), list):
        DEFECTS.append(f"({tag}) 200 but result.groups missing/not array — "
                       f"result-completeness violation (R40 lesson) — "
                       f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
        return
    gs = res["groups"]
    if len(gs) > LIMIT:
        DEFECTS.append(f"({tag}) {len(gs)} groups > limit {LIMIT} — "
                       f"Type4_StateLogicViolation")
    for g in gs:
        gid = str(g.get("id"))
        if gid not in KNOWN:
            DEFECTS.append(f"({tag}) group id {gid!r} outside the written domain "
                           f"{sorted(KNOWN)} — fabricated group — "
                           f"Type4_StateLogicViolation")
        hits = [h.get("id") for h in g.get("hits", []) if isinstance(h, dict)]
        if len(hits) > PER_THREAD:
            DEFECTS.append(f"({tag}) group {gid} has {len(hits)} hits > "
                           f"group_size {PER_THREAD} — Type4_StateLogicViolation")
        if len(hits) != len(set(map(str, hits))):
            DEFECTS.append(f"({tag}) group {gid} contains duplicate hit ids "
                           f"{hits} — partial-commit double-read — "
                           f"Type4_StateLogicViolation")


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
    C = "spqg6_" + TS + "_col"
    print(f"[config] T={T} threads, PER_THREAD={PER_THREAD}, LIMIT={LIMIT}")

    try:
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        pts = [{"id": pid, "vector": vec_for(pid), "payload": {"grp": g}}
               for g, ids in POINT_MAP.items() for pid in ids]
        s_up, raw_up = safe_request("PUT", "upsert_points", path_params={"name": C},
                                    body={"points": pts},
                                    query_params={"wait": "true"})
        print(f"[seed base 12] status={s_up}")
        if s_up not in (200, 201):
            return "SCRIPT_ERROR"
        s_ix, _ = safe_request("PUT", "create_index", path_params={"name": C},
                               body={"field_name": "grp", "field_schema": "keyword"},
                               query_params={"wait": "true"})
        if s_ix not in (200, 201):
            return "SCRIPT_ERROR"

        tally = {}
        threads = [threading.Thread(target=writer_thread, args=(C, t, tally))
                   for t in range(T)]
        q_tally = {}
        n_queries = 0
        t0 = time.time()
        for th in threads:
            th.start()
        while any(th.is_alive() for th in threads):
            s, raw = safe_request("POST", "query_groups", path_params={"name": C},
                                  body={"query": [1.0, 1.0, 1.0, 1.0],
                                        "group_by": "grp", "limit": LIMIT,
                                        "group_size": PER_THREAD,
                                        "params": {"exact": True}})
            q_tally[s] = q_tally.get(s, 0) + 1
            n_queries += 1
            if handle_transport("inflight-query", s, raw):
                break
            if s == 200:
                check_inflight_groups(raw, "inflight-query")
            elif 400 <= s <= 499:
                WARNINGS.append(f"(inflight-query) status {s} during concurrent "
                                f"writes — raw={str(raw)[:120]}")
            time.sleep(0.02)
        for th in threads:
            th.join()
        print(f"[race] writers done in {time.time()-t0:.1f}s; upsert tally="
              f"{dict(sorted(tally.items()))}; query tally={dict(sorted(q_tally.items()))} "
              f"({n_queries} queries)")
        if ABORT[0]:
            return verdict()

        # ---- final consistency leg ----
        time.sleep(2)  # eventual-consistency settle (spec pattern)
        expected_total = 12 + T * PER_THREAD
        cnt = exact_count(C)
        print(f"[final count] {cnt} (expected {expected_total})")
        if isinstance(cnt, int) and cnt != expected_total:
            DEFECTS.append(f"(final) exact count {cnt} != {expected_total} after "
                           f"concurrent upserts — lost/duplicated writes — "
                           f"Type4_StateLogicViolation")

        expected_part = {g: sorted(POINT_MAP[g]) for g in BASE_GROUPS}
        for t in range(T):
            expected_part[CONC_GROUPS[t]] = sorted(
                1000 + t * 10 + j for j in range(1, PER_THREAD + 1))
        s_f, r_f = safe_request("POST", "query_groups", path_params={"name": C},
                                body={"query": [1.0, 1.0, 1.0, 1.0],
                                      "group_by": "grp",
                                      "limit": 4 + T + 2,
                                      "group_size": PER_THREAD,
                                      "params": {"exact": True}})
        print(f"[final groups] status={s_f} raw={str(r_f)[:300]}")
        if not handle_transport("final-groups", s_f, r_f) and s_f == 200:
            try:
                body = json.loads(r_f)
                gs = body.get("result", {}).get("groups", [])
            except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
                gs = None
            if not isinstance(gs, list):
                DEFECTS.append("(final) 200 but result.groups missing/not array — "
                               "result-completeness violation — "
                               "Type4_StateLogicViolation")
            else:
                part = {str(g.get("id")): sorted(h.get("id") for h in g.get("hits", [])
                                                 if isinstance(h, dict)) for g in gs}
                print(f"[final partition] {part}")
                for gid in expected_part:
                    if part.get(gid) != expected_part[gid]:
                        DEFECTS.append(f"(final) group {gid} hits {part.get(gid)} "
                                       f"!= expected {expected_part[gid]} — "
                                       f"concurrent write lost/duplicated — "
                                       f"Type4_StateLogicViolation")
                extra = [g for g in part if g not in expected_part]
                if extra:
                    DEFECTS.append(f"(final) unexpected groups {extra} — "
                                   f"Type4_StateLogicViolation")
                if not DEFECTS:
                    print("[final] OK: complete partition with all concurrent "
                          "group values present")

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
