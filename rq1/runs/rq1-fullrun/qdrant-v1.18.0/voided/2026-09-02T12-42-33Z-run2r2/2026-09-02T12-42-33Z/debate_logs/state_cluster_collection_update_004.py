#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_cluster_collection_update_004
# strategy: concurrent
# endpoint: cluster+collection+update
# constraint_ids: qdrant_state_cluster_collection_update_001, qdrant_behavioral_cluster_collection_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/update-collection-cluster
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 4 (concurrent-operation attack) on POST
  /collections/{name}/cluster (cluster+collection+update; URL from
  raw_knowledge api_endpoints[].url). Phase 1 — duplicate-acceptance race
  (G6: duplicate submission is the strongest breaker of the
  "accepted-exactly-once" invariant): T threads synchronized on a Barrier
  submit the SAME create_sharding_key operation against a
  sharding_method=custom collection; the duplicate-key promise (400) must
  survive the race — two or more 2xx = the same shard key accepted twice
  (Type4). Phase 2 — invalid-op spam + concurrent observers: T threads
  submit ghost-peer move_shard ops (must all be 4xx; any 2xx = Type1)
  while T threads read cluster info (must stay 200; 404 = state loss).
  Sporadic 5xx are reproduced once before judging (race false-positive
  guard); a reproduced 5xx with /healthz alive = Type3.
  # Blindspot: BS-03 Concurrency Blindness (concurrent updates corrupt state)
  [chunk_cluster+collection+update coverage: concurrent x
   qdrant_state_cluster_collection_update_001 (accepted-exactly-once /
   observability under concurrency) + qdrant_behavioral_cluster_collection_update_001
   (400-leg under race)]
Oracle: duplicate create_sharding_key under Barrier(T) -> at most one 2xx;
  >= 2 x 2xx = Type4_StateLogicViolation; ghost-peer move_shard under
  concurrency -> all 4xx (any 2xx = Type1_IllegalSuccess); concurrent GET
  cluster info -> 200 (404 = Type4 state loss); 5xx = Type3 only when
  reproduced AND /healthz alive
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

NTHREADS = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "20"))
GHOST_PEER = 987654


def safe_request(method, path_key, path_params=None, body=None, query_params=None):
    """All HTTP through the runtime; kept in this exact call form so the
    inline liveness probes (GET healthz) stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params)


def jload(raw):
    try:
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}


def result_node(raw):
    b = jload(raw)
    r = b.get("result") if isinstance(b, dict) else None
    return r if isinstance(r, dict) else None


def reproduce_5xx(op_label, op_body, name):
    """One sequential replay of a 5xx'd request: reproduced -> True."""
    try:
        s, raw = safe_request("POST", "collection_cluster",
                              path_params={"name": name}, body=op_body)
    except Exception:
        return False
    print(f"[reproduce {op_label}] status={s} raw={raw[:200]}")
    return 500 <= s <= 599


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sccu4_" + TS + "_"
    C = PFX + "col"
    KEY = PFX + "shardkey"
    DEFECTS = []
    results = []  # (phase, label, status)

    try:
        # custom-sharded collection so create_sharding_key is a VALID op here
        cs, craw = safe_request(
            "PUT", "create_collection", path_params={"name": C},
            body={"vectors": {"size": 4, "distance": "Cosine"},
                  "sharding_method": "custom"})
        custom_ok = cs in (200, 201, 409)
        print(f"[setup create custom] status={cs} ok={custom_ok} "
              f"raw={craw[:200]}")
        if not custom_ok:
            # phase 2 needs a live collection, any sharding mode
            ok, err = rt.setup_default(C, 4, "Cosine")
            if not ok:
                print(f"SETUP_ERROR create {C}: {err}")
                return "SCRIPT_ERROR"

        # ---- Phase 1: duplicate create_sharding_key race ----
        if custom_ok:
            barrier1 = threading.Barrier(NTHREADS)
            dup_op = {"create_sharding_key": {"shard_key": KEY,
                                              "shards_number": 1,
                                              "replication_factor": 1}}

            def dup_worker():
                try:
                    barrier1.wait(timeout=30)
                except threading.BrokenBarrierError:
                    return
                try:
                    s, raw = safe_request("POST", "collection_cluster",
                                          path_params={"name": C},
                                          body=dup_op)
                    results.append(("p1", "dup_create", s))
                except Exception as e:
                    results.append(("p1", "dup_create", f"EXC:{e}"))

            threads = [threading.Thread(target=dup_worker)
                       for _ in range(NTHREADS)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            p1 = [r for r in results if r[0] == "p1"]
            n2xx = sum(1 for r in p1 if isinstance(r[2], int)
                       and 200 <= r[2] < 300)
            n5xx = sum(1 for r in p1 if isinstance(r[2], int)
                       and 500 <= r[2] <= 599)
            print(f"[p1 summary] 2xx={n2xx} 5xx={n5xx} of {len(p1)} "
                  f"statuses={[r[2] for r in p1]}")
            if n2xx >= 2:
                DEFECTS.append(
                    f"(p1) duplicate create_sharding_key '{KEY}' accepted "
                    f"{n2xx} times concurrently (statuses="
                    f"{[r[2] for r in p1]}) — duplicate-key 400 promise broken "
                    f"under race — Type4_StateLogicViolation"
                )
            if n5xx >= 1:
                hs, hraw = safe_request("GET", "healthz")
                print(f"[p1 liveness] healthz status={hs} "
                      f"raw={str(hraw)[:120]}")
                if hs != 200:
                    return "SCRIPT_ERROR"
                if n5xx >= 2 or reproduce_5xx("dup_create", dup_op, C):
                    DEFECTS.append(
                        f"(p1) {n5xx} 5xx responses on concurrent duplicate "
                        f"create_sharding_key (reproduced, service alive per "
                        f"/healthz) — Type3_RuntimeFailure"
                    )
                else:
                    print("ENV_ISSUE: single sporadic 5xx not reproduced — "
                          "recorded, not judged")
            # observability note (judged hard in 006): key visible in shards?
            try:
                vs, vraw = safe_request("GET", "update_shards",
                                        path_params={"name": C})
                print(f"[p1 observability] GET shards status={vs} "
                      f"key_present={KEY in (vraw or '')}")
            except Exception:
                pass
        else:
            print("ENV_ISSUE: custom sharding not available — phase 1 "
                  "(duplicate race) skipped; phase 2 proceeds")

        # ---- Phase 2: invalid-op spam + concurrent cluster-info reads ----
        barrier2 = threading.Barrier(2 * NTHREADS)
        ghost_op = {"move_shard": {"shard_id": 0, "to_peer_id": GHOST_PEER,
                                   "from_peer_id": GHOST_PEER + 1}}

        def spam_worker():
            try:
                barrier2.wait(timeout=30)
            except threading.BrokenBarrierError:
                return
            for _ in range(3):
                try:
                    s, raw = safe_request("POST", "collection_cluster",
                                          path_params={"name": C},
                                          body=ghost_op)
                    results.append(("p2", "ghost_move", s))
                except Exception as e:
                    results.append(("p2", "ghost_move", f"EXC:{e}"))

        def read_worker():
            try:
                barrier2.wait(timeout=30)
            except threading.BrokenBarrierError:
                return
            for _ in range(3):
                try:
                    s, raw = safe_request("GET", "collection_cluster",
                                          path_params={"name": C})
                    results.append(("p2", "info_read", s))
                except Exception as e:
                    results.append(("p2", "info_read", f"EXC:{e}"))

        threads = []
        for _ in range(NTHREADS):
            threads.append(threading.Thread(target=spam_worker))
            threads.append(threading.Thread(target=read_worker))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        p2 = [r for r in results if r[0] == "p2"]
        g = [r for r in p2 if r[1] == "ghost_move" and isinstance(r[2], int)]
        rd = [r for r in p2 if r[1] == "info_read" and isinstance(r[2], int)]
        g2xx = [r for r in g if 200 <= r[2] < 300]
        g5 = [r for r in g if 500 <= r[2] <= 599]
        rd_bad = [r for r in rd if r[2] not in (200, 404)]
        print(f"[p2 summary] ghost_move 2xx={len(g2xx)} 5xx={len(g5)} "
              f"of {len(g)}; info_read non-200/404={len(rd_bad)} of {len(rd)}")
        if g2xx:
            DEFECTS.append(
                f"(p2) ghost-peer move_shard accepted {len(g2xx)} times under "
                f"concurrency (statuses={[r[2] for r in g2xx]}) — 400 promise "
                f"broken — Type1_IllegalSuccess"
            )
        if g5 or rd_bad:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[p2 liveness] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            n5_total = len(g5) + len([r for r in rd_bad
                                      if 500 <= r[2] <= 599])
            if n5_total >= 2 or reproduce_5xx("ghost_move", ghost_op, C):
                DEFECTS.append(
                    f"(p2) {n5_total} 5xx responses under concurrent "
                    f"cluster-op/read load (reproduced or >=2, service alive "
                    f"per /healthz) — Type3_RuntimeFailure"
                )
            else:
                print("ENV_ISSUE: single sporadic 5xx not reproduced — "
                      "recorded, not judged")
        rd404 = [r for r in rd if r[2] == 404]
        if rd404:
            DEFECTS.append(
                f"(p2) cluster info returned 404 on live collection '{C}' "
                f"{len(rd404)} times during concurrent ops (nothing deleted "
                f"it) — state loss under concurrency — "
                f"Type4_StateLogicViolation"
            )

        # final reconciliation: info readable, no transfer pollution
        fs, fraw = safe_request("GET", "collection_cluster",
                                path_params={"name": C})
        print(f"[final info] status={fs} raw={fraw[:300]}")
        if fs == 200:
            node = result_node(fraw)
            transfers = node.get("shard_transfers") \
                if isinstance(node, dict) else None
            if not isinstance(transfers, list) or transfers:
                DEFECTS.append(
                    f"(final) shard_transfers polluted after concurrency: "
                    f"{transfers!r} — Type4_StateLogicViolation"
                )

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        try:
            rt.drop_collection(C)
        except Exception:
            pass


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
