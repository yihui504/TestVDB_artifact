#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_delete_004
# strategy: concurrent
# endpoint: points+delete
# constraint_ids: qdrant_state_points_delete_001, qdrant_bc_delete_points_invisibility_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/delete-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: concurrent-operation attack (Strategy 4, Blindspot BS-03
  Concurrency State Blindness — threat-model attack order for this
  endpoint lists "concurrent delete + upsert") x
  qdrant_state_points_delete_001 + qdrant_bc_delete_points_invisibility_001.
  Thread counts derive from TESTVDB_CONCURRENT_THREADS (default 10).
  Phase A (the race, mutation justification per G6: same-id UPSERT vs
  FILTER-DELETE races hit exactly the WAL apply-ordering window where a
  delete landing between an upsert's staging and commit can be lost or a
  deleted point resurrected — the classic zombie/lost-update window that
  BS-03 says the team underestimates): W writer threads repeatedly upsert
  DISJOINT id slices of the 24 seeded ids while D deleter threads
  round-robin filter-deletes (grp=a, grp=b, matches-all any[a,b]) with
  wait=true. Every racing op targets an EXISTING collection with a valid
  body, so any non-200 is a signal (5xx with service alive = Type3).
  Deterministic post-quiescence reconciliation: after ALL threads join,
  one final all-24-id upsert (wait=true) must leave exact count == 24 and
  batch-get must return each of the 24 ids exactly once (the final write
  postdates every delete, so nothing may be missing, duplicated, or
  zombified). Phase B (disjoint concurrent deletes): B threads delete
  disjoint id chunks covering all 24 ids concurrently (wait=true) -> all
  200, exact count == 0, batch-get and scroll return no points (a
  surviving id = lost delete — Type4; the count face disagreeing with the
  read faces = internal state inconsistency — Type4).
  [chunk_points+delete coverage: concurrent x
  qdrant_state_points_delete_001 + qdrant_bc_delete_points_invisibility_001
  (upsert-vs-filter-delete race + post-quiescence reconciliation +
  disjoint concurrent deletes + read-face agreement)]
Oracle: Phase A -> every racing upsert/delete returns 200 on the existing
  collection (any 5xx with /healthz alive = Type3_RuntimeFailure; any
  other non-200 on a valid racing op = Type4_StateLogicViolation); after
  quiescence the final upsert returns 200 and exact count == 24 with
  batch-get ids exactly {0..23} each once (count != 24 or missing/
  duplicate id = Type4_StateLogicViolation); Phase B -> every disjoint
  delete returns 200 (idempotent-success promise), exact count == 0,
  batch-get == [] and scroll returns no points (survivor =
  Type4_StateLogicViolation; 5xx alive = Type3_RuntimeFailure); transport
  failure -> liveness re-check before any verdict.
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

# URLs used VERBATIM from raw_knowledge api_endpoints[]:
#   {"endpoint_name": "Delete Points", "method": "POST",
#    "url": "/collections/{collection_name}/points/delete"}   -> runtime delete_points
#   {"endpoint_name": "Retrieve Points (batch get)", "method": "POST",
#    "url": "/collections/{collection_name}/points"}          -> get_points_by_ids
rt.PATHS["get_points_by_ids"] = "/collections/{collection_name}/points"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if k in ('get_points_by_ids', 'delete_points')]}")

THREADS = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10") or "10")
if THREADS < 2:
    THREADS = 2
N_IDS = 24
WRITER_ROUNDS = 6

DEFECTS = []
ABORT = [False]
LOCK = threading.Lock()


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=60):
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
    print(f"[liveness {tag}] healthz probe required")
    _hs, _hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={_hs} raw={str(_hraw)[:120]}")
    return _hs == 200


def result_of(raw):
    try:
        return json.loads(raw).get("result")
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        return None


def record_race_error(tag, s, raw):
    """Non-200 on a valid racing op (collection exists, valid body)."""
    with LOCK:
        if 500 <= s <= 599:
            if liveness(tag):
                DEFECTS.append(f"({tag}) racing op returned {s} with service "
                               f"alive — Type3_RuntimeFailure — "
                               f"raw={str(raw)[:150]}")
            else:
                ABORT[0] = True
        else:
            DEFECTS.append(f"({tag}) racing op returned unexpected {s} — "
                           f"Type4_StateLogicViolation — "
                           f"raw={str(raw)[:150]}")


def transport_failed(tag, s):
    if s == 0:
        if not liveness(tag):
            ABORT[0] = True
        return True
    return False


def partition(ids, k):
    out = [[] for _ in range(k)]
    for i, x in enumerate(ids):
        out[i % k].append(x)
    return out


def vec(i):
    return [0.1 + 0.01 * (i % 10), 0.5, 0.75, 1.0]


def grp_of(i):
    return "a" if i % 2 == 0 else "b"


def writer_thread(coll, slice_ids, tid):
    tag = f"writer{tid}"
    for rnd in range(WRITER_ROUNDS):
        body = {"points": [{"id": i, "vector": vec(i),
                            "payload": {"grp": grp_of(i), "n": i}}
                           for i in slice_ids]}
        s, raw = safe_request("PUT", "upsert_points",
                              path_params={"name": coll}, body=body,
                              query_params={"wait": "true"})
        if transport_failed(f"{tag} r{rnd}", s):
            return
        if s != 200:
            record_race_error(f"{tag} r{rnd}", s, raw)
        time.sleep(0.02)


def deleter_thread(coll, stop_event, tid, filters):
    tag = f"deleter{tid}"
    it = 0
    while not stop_event.is_set() and it < 300:
        flt = filters[it % len(filters)]
        s, raw = safe_request("POST", "delete_points",
                              path_params={"name": coll},
                              body={"filter": flt},
                              query_params={"wait": "true"})
        if transport_failed(f"{tag} it{it}", s):
            return
        if s != 200:
            record_race_error(f"{tag} it{it}", s, raw)
        it += 1
        time.sleep(0.02)


def phase_b_deleter(coll, chunk, tid):
    tag = f"B-deleter{tid}"
    s, raw = safe_request("POST", "delete_points",
                          path_params={"name": coll},
                          body={"points": chunk},
                          query_params={"wait": "true"})
    if transport_failed(tag, s):
        return
    if s != 200:
        record_race_error(tag, s, raw)


def exact_count(tag, coll):
    s, raw = safe_request("POST", "count", path_params={"name": coll},
                          body={"exact": True})
    print(f"[{tag} count] status={s} raw={str(raw)[:160]}")
    if transport_failed(tag, s):
        return None
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) count returned {s} with service alive "
                           f"— Type3_RuntimeFailure")
        return None
    if s != 200:
        print(f"SETUP_ERROR: {tag} count returned {s}")
        return None
    res = result_of(raw)
    cnt = res.get("count") if isinstance(res, dict) else None
    if isinstance(cnt, bool) or not isinstance(cnt, int):
        print(f"SETUP_ERROR: {tag} count result.count missing")
        return None
    return cnt


def batch_get_ids(tag, coll, ids):
    s, raw = safe_request("POST", "get_points_by_ids",
                          path_params={"collection_name": coll},
                          body={"ids": ids}, timeout=60)
    print(f"[{tag} batch-get {len(ids)} ids] status={s} raw={str(raw)[:200]}")
    if transport_failed(tag, s):
        return None
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) batch-get returned {s} with service "
                           f"alive — Type3_RuntimeFailure")
        return None
    if s != 200:
        print(f"SETUP_ERROR: {tag} batch-get returned {s}")
        return None
    res = result_of(raw)
    if not isinstance(res, list):
        print(f"SETUP_ERROR: {tag} batch-get result not an array")
        return None
    return [p.get("id") for p in res if isinstance(p, dict)]


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spdel4_" + TS + "_"
    C = PFX + "col"
    DIM = 4
    ALL = list(range(N_IDS))

    n_writers = max(2, min(6, THREADS // 2))
    n_deleters = max(2, min(4, THREADS // 3))
    n_b = max(2, min(12, THREADS))
    print(f"[config] THREADS={THREADS} writers={n_writers} "
          f"deleters={n_deleters} phaseB={n_b}")

    try:
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        s, raw = safe_request("PUT", "upsert_points",
                              path_params={"name": C},
                              body={"points": [
                                  {"id": i, "vector": vec(i),
                                   "payload": {"grp": grp_of(i), "n": i}}
                                  for i in ALL]},
                              query_params={"wait": "true"})
        print(f"[seed upsert {N_IDS} pts] status={s} raw={str(raw)[:160]}")
        if s != 200:
            print("SETUP_ERROR: seed upsert failed")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if exact_count("seed", C) != N_IDS:
            print("SETUP_ERROR: seed count != N")
            return "SCRIPT_ERROR"

        # ---- Phase A: upsert-vs-filter-delete race ----
        stop_event = threading.Event()
        writer_slices = partition(ALL, n_writers)
        deleter_filters = [
            {"must": [{"key": "grp", "match": {"value": "a"}}]},
            {"must": [{"key": "grp", "match": {"value": "b"}}]},
            {"must": [{"key": "grp", "match": {"any": ["a", "b"]}}]},
        ]
        threads = []
        for w in range(n_writers):
            t = threading.Thread(target=writer_thread,
                                 args=(C, writer_slices[w], w))
            threads.append(t)
            t.start()
        for d in range(n_deleters):
            t = threading.Thread(target=deleter_thread,
                                 args=(C, stop_event, d, deleter_filters))
            threads.append(t)
            t.start()
        # wait for writers, then let deleters drain and join
        for t in threads[:n_writers]:
            t.join()
        stop_event.set()
        for t in threads[n_writers:]:
            t.join()
        print("[Phase A] all racing threads joined")

        # deterministic reconciliation: final write postdates every delete
        s, raw = safe_request("PUT", "upsert_points",
                              path_params={"name": C},
                              body={"points": [
                                  {"id": i, "vector": vec(i),
                                   "payload": {"grp": grp_of(i), "n": i}}
                                  for i in ALL]},
                              query_params={"wait": "true"}, timeout=60)
        print(f"[Phase A final upsert] status={s} raw={str(raw)[:160]}")
        if transport_failed("A-final-upsert", s):
            return "SCRIPT_ERROR"
        if s != 200:
            DEFECTS.append(f"(A-final) final all-id upsert returned {s} "
                           f"(expected 200) — Type4_StateLogicViolation")
        cnt = exact_count("A-final", C)
        if cnt is not None and cnt != N_IDS:
            DEFECTS.append(f"(A-final) exact count {cnt} != {N_IDS} after "
                           f"post-quiescence final upsert — lost/zombified "
                           f"points from the race — "
                           f"Type4_StateLogicViolation")
        got = batch_get_ids("A-final", C, ALL)
        if got is not None:
            if set(got) != set(ALL):
                missing = sorted(set(ALL) - set(got))
                extra = sorted(set(got) - set(ALL))
                DEFECTS.append(f"(A-final) batch-get ids mismatch after race "
                               f"(missing={missing}, unexpected={extra}) — "
                               f"Type4_StateLogicViolation")
            if len(got) != len(set(got)):
                DEFECTS.append(f"(A-final) batch-get returned duplicate ids "
                               f"{sorted(got)} — Type4_StateLogicViolation")

        # ---- Phase B: disjoint concurrent deletes cover all ids ----
        chunks = [c for c in partition(ALL, n_b) if c]
        threads = []
        for b, chunk in enumerate(chunks):
            t = threading.Thread(target=phase_b_deleter, args=(C, chunk, b))
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
        print(f"[Phase B] {len(chunks)} disjoint deleter threads joined")

        cnt = exact_count("B-final", C)
        if cnt is not None and cnt != 0:
            DEFECTS.append(f"(B-final) exact count {cnt} != 0 after disjoint "
                           f"concurrent deletes of every id — lost delete — "
                           f"Type4_StateLogicViolation")
        got = batch_get_ids("B-final", C, ALL)
        if got is not None and got:
            DEFECTS.append(f"(B-final) batch-get leaked ids "
                           f"{sorted(set(got))} after concurrent delete-all "
                           f"— zombie — Type4_StateLogicViolation")
        s, raw = safe_request("POST", "scroll", path_params={"name": C},
                              body={"limit": N_IDS + 5, "with_payload": False})
        print(f"[B-final scroll] status={s} raw={str(raw)[:200]}")
        if not transport_failed("B-final-scroll", s):
            if 500 <= s <= 599:
                if liveness("B-final-scroll"):
                    DEFECTS.append("(B-final scroll) returned "
                                   f"{s} with service alive — "
                                   f"Type3_RuntimeFailure")
            elif s == 200:
                res = result_of(raw)
                pts = res.get("points") if isinstance(res, dict) else None
                if isinstance(pts, list) and pts:
                    DEFECTS.append(f"(B-final scroll) leaked "
                                   f"{len(pts)} points after delete-all — "
                                   f"read faces disagree with count — "
                                   f"Type4_StateLogicViolation")

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        if ABORT[0]:
            print("ABORT: environment/transport unavailable mid-run")
            return "SCRIPT_ERROR"
        return "NO_DEFECT"
    finally:
        try:
            rt.drop_collection(C)
        except Exception:
            pass


if __name__ == "__main__":
    try:
        _v = main()
    except Exception:
        import traceback
        traceback.print_exc()
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
