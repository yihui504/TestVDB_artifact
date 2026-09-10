#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_batch_concurrent_010
# strategy: concurrent
# endpoint: points+batch
# constraint_ids: qdrant_state_points_batch_001
# source_url: https://qdrant.tech/documentation/manage-data/points/
# doc_version: current (site latest; no version archive)
"""
Attack: concurrent-operation attack (Strategy 4, Blindspot BS-03) at batch
  granularity x qdrant_state_points_batch_001 "operations are executed in
  order inside one batch request". Thread count comes from
  TESTVDB_CONCURRENT_THREADS (default 10). Three phases: (P1) T threads
  each submit ONE batch of 5 upserts over DISJOINT id ranges -> all must
  return 200 and the exact count must equal T*5 (no loss, no duplication);
  (P2) all T threads submit the IDENTICAL single-upsert batch (id 5000,
  thread-tagged payload) concurrently -> the id must end up EXACTLY once
  and readable with one of the written payloads (concurrent identical
  batches converge idempotently); (P3) opposing concurrency — threads
  alternate between batch-DELETE and batch-UPSERT of the SAME shared id
  set D for several rounds; afterwards the two read faces must AGREE:
  the exact count must equal fixed_points + |visible(D)| (count/get
  divergence = internal state inconsistency). Any 5xx during the races
  is a Type3 signal after liveness re-check.
  [chunk_points+batch coverage: concurrent x qdrant_state_points_batch_001
  (disjoint batch upserts + identical-batch convergence + opposing
  delete/upsert races + read-face agreement)]
Oracle: P1 -> every batch 200 and exact count == T*5 (lower count = lost
  writes, higher = duplicated — Type4_StateLogicViolation; any 4xx on a
  valid disjoint batch or 5xx with /healthz alive = defect, 5xx recorded
  as Type3_RuntimeFailure); P2 -> id 5000 appears exactly once, GET 200
  with payload {"w": t} for some t in [0, T), count == T*5+1; P3 -> no
  5xx with service alive, and exact_count == T*5+1+|visible(D)| (the
  count face disagreeing with the batch-get face =
  Type4_StateLogicViolation); transport failure -> liveness re-check
  before any verdict.
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

# URLs registered VERBATIM from raw_knowledge api_endpoints[]:
#   {"path": "points+batch", "method": "POST",
#    "url": "/collections/{collection_name}/points/batch"}
#   {"path": "points+get", "method": "POST",
#    "url": "/collections/{collection_name}/points"}
rt.PATHS["batch_update"] = "/collections/{collection_name}/points/batch"
rt.PATHS["get_points_by_ids"] = "/collections/{collection_name}/points"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if k in ('batch_update', 'get_points_by_ids')]}")

THREADS = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10") or "10")
if THREADS < 2:
    THREADS = 2

DEFECTS = []
ABORT = [False]


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


def exact_count(tag, coll):
    s, raw = safe_request("POST", "count", path_params={"name": coll},
                          body={"exact": True})
    print(f"[{tag} count] status={s} raw={str(raw)[:160]}")
    if s == 0 or 500 <= s <= 599:
        if s == 0 and not liveness(tag):
            ABORT[0] = True
            return None
        if 500 <= s <= 599 and liveness(tag):
            DEFECTS.append(f"({tag}) count returned {s} with service alive "
                           f"— Type3_RuntimeFailure")
            return None
        ABORT[0] = True
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


def visible_ids(tag, coll, ids):
    s, raw = safe_request("POST", "get_points_by_ids",
                          path_params={"collection_name": coll},
                          body={"ids": ids, "with_payload": False})
    print(f"[{tag} get {len(ids)} ids] status={s} raw={str(raw)[:240]}")
    if s == 0:
        if not liveness(tag):
            ABORT[0] = True
        return None
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) batch-get returned {s} with service "
                           f"alive — Type3_RuntimeFailure")
        else:
            ABORT[0] = True
        return None
    if s != 200:
        print(f"SETUP_ERROR: {tag} batch-get returned {s}")
        return None
    res = result_of(raw)
    if not isinstance(res, list):
        print(f"SETUP_ERROR: {tag} batch-get result not a list")
        return None
    return set(p.get("id") for p in res
               if isinstance(p, dict) and "id" in p)


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spbx10_" + TS + "_"
    C = PFX + "col"
    DIM = 4

    def vec(x):
        return [float(x), 0.5, 0.75, 1.0]

    def batch_upsert_op(points):
        return {"upsert": {"points": points}}

    try:
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"

        # ---- P1: T concurrent batches over disjoint id ranges ----
        p1_errors = []
        p1_counts = []

        def p1_worker(t):
            base = (t + 1) * 1000
            pts = [{"id": base + j, "vector": vec(j),
                    "payload": {"t": t, "j": j}} for j in range(5)]
            try:
                s, raw = safe_request("POST", "batch_update",
                                      path_params={"collection_name": C},
                                      body={"operations": [batch_upsert_op(pts)]},
                                      query_params={"wait": "true"})
                print(f"[P1 t{t}] status={s} raw={str(raw)[:120]}")
                if s == 0:
                    if not liveness(f"P1 t{t}"):
                        ABORT[0] = True
                    else:
                        p1_errors.append(f"t{t}: transport failure")
                elif 500 <= s <= 599:
                    if liveness(f"P1 t{t}"):
                        p1_errors.append(f"t{t}: HTTP {s}")
                elif s != 200:
                    p1_errors.append(f"t{t}: HTTP {s} on valid disjoint "
                                     f"batch — raw={str(raw)[:100]}")
            except Exception as e:
                p1_errors.append(f"t{t}: exception {e}")

        threads = [threading.Thread(target=p1_worker, args=(t,))
                   for t in range(THREADS)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        time.sleep(2)  # allow eventual consistency before adjudication
        for e in p1_errors:
            DEFECTS.append(f"(P1) concurrent batch error — {e} — "
                           f"Type3/Type4 (concurrent valid batches must "
                           f"all succeed)")
        cnt = exact_count("P1", C)
        expected_p1 = THREADS * 5
        if cnt is not None and cnt != expected_p1:
            DEFECTS.append(f"(P1) exact count {cnt} != {expected_p1} "
                           f"(threads {THREADS} x 5 points) — concurrent "
                           f"batch writes lost/duplicated — "
                           f"Type4_StateLogicViolation")
        elif cnt is not None:
            print(f"[P1] OK: count == {expected_p1}")

        # ---- P2: T concurrent IDENTICAL single-upsert batches (id 5000) ----
        def p2_worker(t):
            try:
                s, raw = safe_request("POST", "batch_update",
                                      path_params={"collection_name": C},
                                      body={"operations": [
                                          batch_upsert_op([{
                                              "id": 5000,
                                              "vector": vec(t),
                                              "payload": {"w": t}}])]},
                                      query_params={"wait": "true"})
                print(f"[P2 t{t}] status={s}")
                if s not in (200,):
                    p1_errors.append(f"P2 t{t}: HTTP {s} raw={str(raw)[:100]}")
            except Exception as e:
                p1_errors.append(f"P2 t{t}: exception {e}")

        threads = [threading.Thread(target=p2_worker, args=(t,))
                   for t in range(THREADS)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        time.sleep(2)
        for e in [x for x in p1_errors if x.startswith("P2")]:
            DEFECTS.append(f"(P2) concurrent identical-batch error — {e} — "
                           f"concurrent identical upsert batches must all "
                           f"succeed (Type3 if 5xx, Type4 if 4xx)")
        vis = visible_ids("P2", C, [5000])
        if vis is not None:
            if vis != {5000}:
                DEFECTS.append(f"(P2) identical-batch id 5000 visible set "
                               f"{vis} != {{5000}} — "
                               f"Type4_StateLogicViolation")
            else:
                print("[P2] OK: identical batches converged to one point")
        cnt = exact_count("P2", C)
        expected_p2 = expected_p1 + 1
        if cnt is not None and cnt != expected_p2:
            DEFECTS.append(f"(P2) exact count {cnt} != {expected_p2} after "
                           f"concurrent identical batches on one id — "
                           f"Type4_StateLogicViolation")

        # ---- P3: opposing concurrent delete/upsert batches on shared ids ----
        shared = [6001 + j for j in range(8)]
        s, raw = safe_request("POST", "batch_update",
                              path_params={"collection_name": C},
                              body={"operations": [
                                  batch_upsert_op([{
                                      "id": pid, "vector": vec(pid % 7),
                                      "payload": {"seed": True}}
                                      for pid in shared])]},
                              query_params={"wait": "true"})
        print(f"[P3 seed] status={s} raw={str(raw)[:120]}")
        if s != 200:
            print(f"SETUP_ERROR: P3 seed status {s}")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"

        def p3_worker(t, rounds=3):
            for r in range(rounds):
                try:
                    if t % 2 == 0:
                        ops = [{"delete": {"points": shared}}]
                    else:
                        ops = [batch_upsert_op([{
                            "id": pid, "vector": vec(r),
                            "payload": {"r": r, "t": t}}
                            for pid in shared])]
                    sx, rawx = safe_request("POST", "batch_update",
                                            path_params={"collection_name": C},
                                            body={"operations": ops},
                                            query_params={"wait": "true"})
                    print(f"[P3 t{t} r{r}] status={sx}")
                    if sx == 0:
                        if not liveness(f"P3 t{t} r{r}"):
                            ABORT[0] = True
                        else:
                            p1_errors.append(
                                f"P3 t{t} r{r}: transport failure")
                    elif 500 <= sx <= 599:
                        if liveness(f"P3 t{t} r{r}"):
                            p1_errors.append(
                                f"P3 t{t} r{r}: HTTP {sx} "
                                f"raw={str(rawx)[:120]}")
                except Exception as e:
                    p1_errors.append(f"P3 t{t} r{r}: exception {e}")

        threads = [threading.Thread(target=p3_worker, args=(t,))
                   for t in range(THREADS)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        time.sleep(2)
        for e in [x for x in p1_errors if x.startswith("P3")]:
            DEFECTS.append(f"(P3) concurrent opposing-batch error — {e} — "
                           f"races must not 5xx/crash — Type3_RuntimeFailure")

        # read-face agreement: count == fixed + |visible(shared)|
        vis = visible_ids("P3", C, shared)
        cnt = exact_count("P3", C)
        if vis is not None and cnt is not None:
            expected_p3 = expected_p2 + len(vis)
            if cnt != expected_p3:
                DEFECTS.append(f"(P3) read-face disagreement: exact count "
                               f"{cnt} != {expected_p3} "
                               f"(fixed {expected_p2} + visible shared "
                               f"{len(vis)}) — count and batch-get faces "
                               f"disagree after concurrent batches — "
                               f"Type4_StateLogicViolation")
            else:
                print(f"[P3] OK: read faces agree "
                      f"(count {cnt}, shared visible {len(vis)})")

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
