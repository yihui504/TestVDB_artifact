#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_percol_count_concurrent_004
# strategy: concurrent
# endpoint: per_collection
# constraint_ids: qdrant_inv_count_consistency_001
# source_url: https://qdrant.tech/documentation/manage-data/points/
# doc_version: current (site latest; no version archive)
"""
Attack: concurrent (Strategy 4: genuine-concurrency verification) x
  qdrant_inv_count_consistency_001 "after inserting N points (wait=true)
  the exact count reflects N". Blindspot: BS-03 Concurrency State
  Blindness — concurrent writes racing inside one collection. T threads
  (TESTVDB_CONCURRENT_THREADS, default 20 for qdrant) start on a
  threading.Barrier (simultaneous start makes the overlap genuine, not
  incidental) and each upsertes M=5 DISJOINT id-addressed points
  (thread k owns ids [k*M, k*M+M)) with wait=true — the disjoint
  partition makes the expected final count deterministic: T*M. After all
  writers finish: (1) settle, then exact count read TWICE — both reads
  must equal T*M and each other (a count that flaps between reads is a
  consistency break); (2) per-partition verification — for every thread
  k, exact count with filter must has_id [k*M, k*M+M) == M, proving no
  partition lost or duplicated rows; the sum of partitions equals the
  whole (partition consistency). Any writer getting non-200, or any
  5xx with /healthz alive, is recorded (Type3); a final count != T*M or
  a partition != M is Type4. This family measured negative on this
  version in the R8 baseline — the adversarial expectation is that the
  invariant HOLDS under genuine concurrency; the verification itself is
  the deliverable.
  [chunk_per_collection coverage: concurrent x
  qdrant_inv_count_consistency_001 (barrier-start disjoint partitions +
  double-read stability + per-partition filtered counts)]
Oracle: every barrier-started writer upsert returns 200 (non-200
  recorded; 5xx with /healthz alive = Type3_RuntimeFailure; transport
  failure -> liveness re-check, alive = Type3, dead = SCRIPT_ERROR);
  final exact count == THREADS*5 on BOTH post-join reads (mismatch or
  flapping = Type4_StateLogicViolation); every per-thread has_id
  filtered count == 5 (partition loss/gain = Type4).
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

THREADS = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "20"))
M = 5  # points per writer thread
EXPECTED = THREADS * M

DEFECTS = []
ABORT = [False]
WRITE_ERRORS = []  # (thread_idx, status, raw_snippet)


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=60):
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
    print(f"[liveness {tag}] healthz probe required")
    _hs, _hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={_hs} raw={str(_hraw)[:120]}")
    return _hs == 200


def writer(barrier, k, coll):
    base = k * M
    pts = [{"id": base + j, "vector": [float(base + j) + 0.1, 0.2, 0.3, 0.4],
            "payload": {"writer": k, "slot": j}} for j in range(M)]
    try:
        barrier.wait(timeout=30)
    except threading.BrokenBarrierError:
        return
    s, raw = safe_request("PUT", "upsert_points",
                          path_params={"name": coll},
                          body={"points": pts},
                          query_params={"wait": "true"})
    print(f"[writer {k}] status={s} raw={str(raw)[:100]}")
    if s != 200:
        WRITE_ERRORS.append((k, s, str(raw)[:120]))


def exact_count(tag, coll, flt=None):
    body = {"exact": True}
    if flt is not None:
        body["filter"] = flt
    s, raw = safe_request("POST", "count", path_params={"name": coll},
                          body=body)
    print(f"[{tag}] status={s} raw={str(raw)[:160]}")
    if s == 0:
        if not liveness(tag):
            ABORT[0] = True
        else:
            DEFECTS.append(f"({tag}) count transport failure with service "
                           f"alive — Type3_RuntimeFailure")
        return None
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) count returned {s} with service alive "
                           f"— Type3_RuntimeFailure — raw={str(raw)[:150]}")
        else:
            ABORT[0] = True
        return None
    if s != 200:
        print(f"SETUP_ERROR: {tag} count returned {s}")
        return None
    try:
        res = json.loads(raw).get("result")
        cnt = res.get("count") if isinstance(res, dict) else None
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        cnt = None
    if isinstance(cnt, bool) or not isinstance(cnt, int):
        print(f"SETUP_ERROR: {tag} count result.count missing — raw={str(raw)[:200]}")
        return None
    return cnt


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sccc4_" + TS + "_"
    C = PFX + "col"
    DIM = 4

    try:
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"

        barrier = threading.Barrier(THREADS)
        threads = [threading.Thread(target=writer, args=(barrier, k, C))
                   for k in range(THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=180)

        # ---- writer-level adjudication ----
        for (k, s, raw) in WRITE_ERRORS:
            if s == 0:
                if not liveness(f"writer {k}"):
                    ABORT[0] = True
                else:
                    DEFECTS.append(f"(writer {k}) transport failure with "
                                   f"service alive — Type3_RuntimeFailure — "
                                   f"raw={raw}")
            elif 500 <= s <= 599:
                if liveness(f"writer {k}"):
                    DEFECTS.append(f"(writer {k}) returned {s} with service "
                                   f"alive — Type3_RuntimeFailure — raw={raw}")
                else:
                    ABORT[0] = True
            else:
                DEFECTS.append(f"(writer {k}) concurrent upsert returned "
                               f"{s} (legal wait=true write must succeed) — "
                               f"Type3_RuntimeFailure — raw={raw}")
        print(f"[writers] {THREADS - len(WRITE_ERRORS)}/{THREADS} returned 200")

        # ---- settle + double-read stability ----
        time.sleep(2)
        c1 = exact_count("final count read1", C)
        c2 = exact_count("final count read2", C)
        if c1 is not None and c1 != EXPECTED:
            DEFECTS.append(f"(final count read1) exact count {c1} != "
                           f"{EXPECTED} after {THREADS}x{M} disjoint "
                           f"wait=true upserts — Type4_StateLogicViolation "
                           f"(qdrant_inv_count_consistency_001)")
        if c2 is not None and c2 != EXPECTED:
            DEFECTS.append(f"(final count read2) exact count {c2} != "
                           f"{EXPECTED} — Type4_StateLogicViolation")
        if c1 is not None and c2 is not None and c1 != c2:
            DEFECTS.append(f"(count stability) two consecutive exact reads "
                           f"disagree: {c1} vs {c2} — no concurrent writers "
                           f"remain — Type4_StateLogicViolation")
        if c1 == EXPECTED:
            print(f"[final count] OK: {c1} == {THREADS}*{M}")

        # ---- per-partition filtered counts ----
        bad_parts = []
        for k in range(THREADS):
            ids = [k * M + j for j in range(M)]
            pk = exact_count(f"partition {k}", C,
                             {"must": [{"has_id": ids}]})
            if pk is None:
                continue  # abort/defect already recorded
            if pk != M:
                bad_parts.append((k, pk))
                DEFECTS.append(f"(partition {k}) has_id filtered exact count "
                               f"{pk} != {M} (ids {ids}) — rows lost or "
                               f"duplicated inside one writer's disjoint "
                               f"partition — Type4_StateLogicViolation")
        if not bad_parts:
            print(f"[partitions] OK: all {THREADS} partitions count == {M}")

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
