#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_cluster_collection_info_004
# strategy: concurrent
# endpoint: cluster+collection+info
# constraint_ids: qdrant_type_cluster_collection_info_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/collection-cluster-info
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (Concurrency State Blindness — concurrent committed writes vs the cluster-info count report)
"""
Attack: Strategy 4 (concurrent operations, point-level) against the
  CollectionClusterInfo report. K threads upsert disjoint id batches
  (wait=true so every batch is committed before its response) into a
  3-shard collection while a reader continuously polls
  GET /collections/{name}/cluster. Mutation-point justification (G6):
  concurrent committed writes across several shards are the load that makes
  per-shard points_count bookkeeping drift — each thread's ack'd batch
  increments disjoint shard counters, the classic lost-update window.
  Judged signals: any upsert 5xx (liveness re-checked -> Type3); reader 5xx
  during writes (>=2 per the reproduction rule -> Type3); reader 200 with a
  degraded six-field shape (>=2 -> Type4); after all threads join and
  settle, the count face (exact) must report K*P points AND the cluster
  info's sum over local_shards points_count must equal the same total —
  disagreement between the two faces = Type4 (the report must reconcile
  with the committed state it reports on).
  [chunk_cluster+collection+info coverage: concurrent(point-level, strategy 4) x
   qdrant_type_cluster_collection_info_001]
Oracle: zero upsert 5xx; zero reader 5xx (>=2 = Type3_RuntimeFailure);
  every reader 200 carries all six fields (>=2 breaks =
  Type4_StateLogicViolation); post-join exact count == sum(local_shards
  points_count) == THREADS*POINTS_PER_THREAD (mismatch = Type4)
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

REQUIRED_FIELDS = ("peer_id", "shard_count", "local_shards", "remote_shards",
                   "shard_transfers", "resharding_operations")
DIM = 4
POINTS_PER_THREAD = 20
REQ_SHARDS = 3


def alive():
    hs, hraw = rt.request("GET", "healthz")
    print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scci4_" + TS + "_"
    C = PFX + "col"
    try:
        n_threads = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10"))
    except ValueError:
        n_threads = 10
    n_threads = max(2, min(n_threads, 50))
    expected = n_threads * POINTS_PER_THREAD

    DEFECTS = []
    lock = threading.Lock()
    stop_evt = threading.Event()
    upsert_5xx = []
    upsert_4xx = []
    env_failures = []
    reader_5xx = []
    reader_shape = []

    def writer(tid):
        base = tid * 100000
        pts = [{"id": base + i,
                "vector": [0.1 * ((base + i) % 5) + 0.01, 0.2, 0.3, 0.4]}
               for i in range(POINTS_PER_THREAD)]
        try:
            s, raw = rt.request("PUT", "upsert_points", {"points": pts},
                                path_params={"name": C},
                                query_params={"wait": "true"})
            if s == 0:
                with lock:
                    env_failures.append(f"W#{tid}: transport {str(raw)[:120]}")
            elif 500 <= s <= 599:
                with lock:
                    upsert_5xx.append(f"W#{tid}: {s} raw={str(raw)[:150]}")
            elif s not in (200, 201):
                with lock:
                    upsert_4xx.append(f"W#{tid}: {s} raw={str(raw)[:150]}")
        except Exception as e:
            with lock:
                env_failures.append(f"W#{tid}: exception {str(e)[:120]}")

    def reader():
        while not stop_evt.is_set():
            try:
                s, raw = rt.request("GET", "collection_cluster",
                                    path_params={"name": C})
            except Exception as e:
                with lock:
                    env_failures.append(f"R: exception {str(e)[:120]}")
                time.sleep(0.02)
                continue
            if s == 0:
                with lock:
                    env_failures.append(f"R: transport {str(raw)[:120]}")
            elif 500 <= s <= 599:
                with lock:
                    reader_5xx.append(f"{s} raw={str(raw)[:150]}")
            elif s == 200:
                try:
                    b = json.loads(raw) if raw else {}
                    node = b.get("result") if isinstance(b, dict) else None
                    if not isinstance(node, dict):
                        with lock:
                            reader_shape.append("200 result not object")
                    else:
                        missing = [f for f in REQUIRED_FIELDS if f not in node]
                        if missing:
                            with lock:
                                reader_shape.append(f"200 missing {missing}")
                except (json.JSONDecodeError, ValueError, TypeError):
                    with lock:
                        reader_shape.append(f"200 unparseable {str(raw)[:120]}")
            time.sleep(0.02)

    try:
        # ---- setup: multi-shard collection so per-shard counters actually split ----
        s, raw = rt.request("PUT", "create_collection", {
            "vectors": {"size": DIM, "distance": "Cosine"},
            "shard_number": REQ_SHARDS,
        }, path_params={"name": C})
        print(f"[create] status={s} threads={n_threads} "
              f"expected_total={expected} raw={raw[:200]}")
        if s not in (200, 201):
            return "SCRIPT_ERROR"

        r_thread = threading.Thread(target=reader, daemon=True)
        r_thread.start()
        w_threads = [threading.Thread(target=writer, args=(t,), daemon=True)
                     for t in range(n_threads)]
        for t in w_threads:
            t.start()
        for t in w_threads:
            t.join(timeout=180)
        stop_evt.set()
        r_thread.join(timeout=30)
        time.sleep(2.0)  # allow settle before the reconciliation read

        # ---- upsert-side failures ----
        if upsert_5xx:
            if alive():
                DEFECTS.append(
                    f"{len(upsert_5xx)} x 5xx on concurrent wait=true upserts — "
                    f"Type3_RuntimeFailure — samples: {upsert_5xx[:3]}"
                )
            else:
                return "SCRIPT_ERROR"
        if upsert_4xx:
            print(f"OBSERVATION: non-2xx upsert dispositions (recorded, not "
                  f"judged): {upsert_4xx[:3]}")

        # ---- reader-side signals (reproduction rule: >=2) ----
        if len(reader_5xx) >= 2:
            DEFECTS.append(
                f"{len(reader_5xx)} x 5xx on cluster-info reads during concurrent "
                f"committed writes — Type3_RuntimeFailure — samples: {reader_5xx[:3]}"
            )
        elif reader_5xx:
            print(f"OBSERVATION (inconclusive, <2): reader 5xx: {reader_5xx}")
        if len(reader_shape) >= 2:
            DEFECTS.append(
                f"{len(reader_shape)} x degraded shape on cluster-info 200s during "
                f"writes — Type4_StateLogicViolation — samples: {reader_shape[:3]}"
            )
        elif reader_shape:
            print(f"OBSERVATION (inconclusive, <2): reader shape: {reader_shape}")

        # ---- reconciliation: count face vs cluster-info face ----
        cs, craw = rt.request("POST", "count", {"exact": True},
                              path_params={"name": C})
        print(f"[count face] status={cs} raw={craw[:200]}")
        cval = None
        if cs == 200:
            try:
                cval = json.loads(craw).get("result", {}).get("count")
            except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
                cval = None
        if not isinstance(cval, int):
            return "SCRIPT_ERROR"
        if cval != expected:
            DEFECTS.append(
                f"count face reports {cval} after {n_threads} threads committed "
                f"{POINTS_PER_THREAD} wait=true points each (expected {expected}) — "
                f"Type4_StateLogicViolation"
            )

        s2, raw2 = rt.request("GET", "collection_cluster", path_params={"name": C})
        print(f"[info face] status={s2} raw={raw2[:400]}")
        if s2 != 200:
            if s2 == 0 or 500 <= s2 <= 599:
                if not alive():
                    return "SCRIPT_ERROR"
            return "SCRIPT_ERROR"
        try:
            node = json.loads(raw2).get("result")
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
            node = None
        if not isinstance(node, dict):
            return "SCRIPT_ERROR"
        lsum, seen = 0, 0
        for e in node.get("local_shards") or []:
            if isinstance(e, dict) and isinstance(e.get("points_count"), int):
                lsum += e["points_count"]
                seen += 1
        print(f"[reconcile] count_face={cval} cluster_info_local_sum={lsum} "
              f"(entries with points_count: {seen}) expected={expected}")
        if seen:
            if lsum != expected or cval != expected:
                DEFECTS.append(
                    f"cluster-info face (local_shards points_count sum={lsum}) "
                    f"disagrees with committed state / count face (={cval}, "
                    f"expected {expected}) — Type4_StateLogicViolation"
                )
        else:
            print("OBSERVATION: no local_shards entry exposes points_count — "
                  "report-side reconciliation skipped")

        if env_failures and not DEFECTS:
            print(f"ENV_ISSUES: {env_failures[:3]}")
            if not alive():
                return "SCRIPT_ERROR"

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        stop_evt.set()
        try:
            rt.drop_collection(C)
        except Exception:
            pass


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
