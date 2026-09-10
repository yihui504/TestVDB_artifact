#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_cluster_peer_delete_004
# strategy: concurrent
# endpoint: cluster+peer+delete
# constraint_ids: qdrant_state_cluster_peer_delete_001, qdrant_behavioral_cluster_peer_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/remove-peer
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (Concurrency State Blindness — concurrent cluster-membership
#   mutations racing the cluster-status reader and the data plane)
"""
Attack: Strategy 4 (concurrent-operation attack) on DELETE
  /cluster/peer/{peer_id} (URL template read verbatim from raw_knowledge
  api_endpoints[].url, registered into rt.PATHS). Mutation-point justification
  (G6): concurrent membership mutations are exactly the window where raft
  consensus bookkeeping can tear — many removal proposals interleaving with
  membership reads is the most destructive timing for a consensus-guarded
  carrier, and a standalone deployment still exercises the guard's graceful
  refusal path under load (refusal must stay 4xx, never 5xx/panic).
  Setup: collection C (unique prefix) with N=40 points, exact count baseline.
  Storm: T threads (TESTVDB_CONCURRENT_THREADS, default 20 per qdrant
  guidance) each issue ITERS=4 removals alternating unique ghost peer ids and
  the deployment's self peer_id (derived from GET /cluster, never hardcoded);
  a reader thread continuously polls GET /cluster. Judged signals: any 2xx
  on a removal carrier = Type1 (invalid-id promise / no-force guard);
  >= 2 5xx from either face (after /healthz liveness) = Type3 (single 5xx =
  inconclusive observation per the reproduction rule); >= 2 membership-flap
  reads (peers set != baseline while no removal was accepted) = Type4; final
  exact count != N = Type4 data-plane corruption; final GET /cluster must be
  200 with the baseline peers set.
  [chunk_cluster+peer+delete coverage: concurrent x
   qdrant_state_cluster_peer_delete_001 (consensus-survival under
   concurrent mutations) + qdrant_behavioral_cluster_peer_delete_001
   (4xx face under load)]
Oracle: under a 20-thread removal storm (ghost + self carriers) every
  removal stays 4xx (any 2xx = Type1_IllegalSuccess; >=2 5xx = Type3 only
  after /healthz liveness), every GET /cluster read stays 200 with the
  baseline peers set (>=2 flips = Type4), and the data plane keeps the exact
  count N (drift = Type4_StateLogicViolation)
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


def load_peer_delete_template():
    """R5 lesson: derive the URL only from raw_knowledge api_endpoints[].url."""
    for _p in Path(__file__).resolve().parents:
        _rk = _p / "raw_knowledge.json"
        if _rk.exists():
            try:
                for _e in json.loads(_rk.read_text(encoding="utf-8")).get("api_endpoints", []):
                    if _e.get("path") == "cluster+peer+delete" and _e.get("url"):
                        return _e["url"]
            except Exception:
                return None
    return None


_PEER_TPL = load_peer_delete_template()
if not _PEER_TPL:
    print("VERDICT: SCRIPT_ERROR - cluster+peer+delete url not derivable from raw_knowledge api_endpoints[].url")
    sys.exit(2)
rt.PATHS["cluster_peer_delete"] = _PEER_TPL
print(f"[url-derived] cluster+peer+delete -> {_PEER_TPL} (raw_knowledge api_endpoints[].url)")


def safe_request(method, path_key, path_params=None, body=None, query_params=None):
    """All HTTP through the runtime; inline liveness probes (GET healthz)
    stay in this exact call form for static-check visibility."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params)


def alive():
    hs, hraw = safe_request("GET", "healthz")
    print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def cluster_snapshot():
    """GET /cluster -> (status, peers_frozenset|None, self_peer_id|None, raw)."""
    s, raw = safe_request("GET", "cluster_status")
    if s != 200:
        return s, None, None, raw
    try:
        b = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return s, None, None, raw
    node = b.get("result") if isinstance(b, dict) else None
    if not isinstance(node, dict):
        return s, None, None, raw
    peers = node.get("peers")
    peers_set = None
    if isinstance(peers, dict):
        peers_set = frozenset(str(k) for k in peers.keys())
    elif isinstance(peers, list):
        ids = []
        for p in peers:
            if isinstance(p, dict) and "peer_id" in p:
                ids.append(str(p["peer_id"]))
            else:
                ids.append(str(p))
        peers_set = frozenset(ids)
    return s, peers_set, node.get("peer_id"), raw


def exact_count(name):
    """POST /collections/{name}/points/count exact -> count|None."""
    s, raw = safe_request("POST", "count", path_params={"name": name},
                          body={"exact": True})
    if s != 200:
        return None
    try:
        b = json.loads(raw) if raw else {}
        node = b.get("result") if isinstance(b, dict) else None
        if isinstance(node, dict) and isinstance(node.get("count"), int):
            return node["count"]
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    return None


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scpd4_" + TS + "_"
    C = PFX + "col"
    N_POINTS = 40
    GHOST_BASE = 987654321100000
    T = max(2, int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "20")))
    ITERS = 4
    DEFECTS = []
    lock = threading.Lock()
    stop_evt = threading.Event()
    bucket = {"del_2xx": [], "del_5xx": [], "del_transport": [],
              "rd_5xx": [], "rd_flap": [], "rd_transport": [], "rd_other": []}

    try:
        # ---- reachability probe (R5: probe first) ----
        s0, peers0, self0, raw0 = cluster_snapshot()
        print(f"[probe GET /cluster] status={s0} self_peer_id={self0} "
              f"peers={sorted(peers0) if peers0 is not None else None} raw={raw0[:200]}")
        if s0 == 0 or s0 != 200:
            if not alive():
                return "SCRIPT_ERROR"
            print(f"ENV_ISSUE: GET /cluster returned {s0} — cluster face not exercisable")
            return "SCRIPT_ERROR"
        if self0 is None:
            print("OBSERVATION: self peer_id not derivable — storm uses ghost ids only")

        # ---- data-plane setup: collection + N points + exact baseline ----
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR create {C}: {err}")
            return "SCRIPT_ERROR"
        pts = [{"id": i, "vector": [0.1, 0.2, 0.3, 0.4]} for i in range(N_POINTS)]
        iok, ierr = rt.insert_points(C, pts)
        if not iok:
            print(f"SETUP_ERROR insert {C}: {ierr}")
            return "SCRIPT_ERROR"
        time.sleep(1.0)  # settle before exact count
        base_count = exact_count(C)
        print(f"[baseline] exact count of {C} = {base_count} (expect {N_POINTS})")
        if base_count != N_POINTS:
            print("ENV_ISSUE: baseline count mismatch before any attack — "
                  "data-plane check disabled, storm still judged")
            base_count = None

        def deleter_thread(tid):
            for i in range(ITERS):
                if stop_evt.is_set():
                    return
                # alternate carriers: unique ghost id / the self peer id
                if self0 is not None and (tid + i) % 2 == 1:
                    pid_desc, pid = f"self:{self0}", self0
                else:
                    pid = GHOST_BASE + tid * 1000 + i
                    pid_desc = f"ghost:{pid}"
                try:
                    s, raw = safe_request("DELETE", "cluster_peer_delete",
                                          path_params={"peer_id": pid})
                except Exception as e:
                    with lock:
                        bucket["del_transport"].append(f"t{tid}i{i}: {str(e)[:100]}")
                    continue
                with lock:
                    if 200 <= s < 300:
                        bucket["del_2xx"].append(
                            f"t{tid}i{i} {pid_desc}: {s} raw={raw[:120]}")
                    elif 500 <= s <= 599:
                        bucket["del_5xx"].append(
                            f"t{tid}i{i} {pid_desc}: {s} raw={raw[:120]}")
                time.sleep(0.02)

        def reader_thread():
            reads = 0
            while not stop_evt.is_set() and reads < T * ITERS * 2:
                reads += 1
                try:
                    s, peers, _self, raw = cluster_snapshot()
                except Exception as e:
                    with lock:
                        bucket["rd_transport"].append(f"r{reads}: {str(e)[:100]}")
                    time.sleep(0.02)
                    continue
                with lock:
                    if s == 0:
                        bucket["rd_transport"].append(f"r{reads}: {str(raw)[:100]}")
                    elif 500 <= s <= 599:
                        bucket["rd_5xx"].append(f"r{reads}: {s} raw={raw[:120]}")
                    elif s == 200:
                        if peers is not None and peers0 is not None and peers != peers0:
                            bucket["rd_flap"].append(
                                f"r{reads}: {sorted(peers)} != {sorted(peers0)}")
                    else:
                        bucket["rd_other"].append(f"r{reads}: {s} raw={raw[:100]}")
                time.sleep(0.02)

        threads = [threading.Thread(target=deleter_thread, args=(t,), daemon=True)
                   for t in range(T)]
        threads.append(threading.Thread(target=reader_thread, daemon=True))
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=180)
        stop_evt.set()
        print(f"[storm done] T={T} x ITERS={ITERS} removal carriers + reader")

        # ---- judged signals ----
        if bucket["del_2xx"]:
            for hit in bucket["del_2xx"][:5]:
                DEFECTS.append(
                    f"(storm) removal carrier accepted under concurrency: {hit} — "
                    f"invalid peer ids must 4xx and self-removal needs force — "
                    f"Type1_IllegalSuccess"
                )
        if len(bucket["del_5xx"]) >= 2:
            if not alive():
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(storm) {len(bucket['del_5xx'])} x 5xx on removal carriers while "
                f"the service is alive per /healthz (graceful 4xx expected) — "
                f"Type3_RuntimeFailure — samples: {bucket['del_5xx'][:3]}"
            )
        elif bucket["del_5xx"]:
            print(f"OBSERVATION (inconclusive, <2 occurrences): del_5xx: "
                  f"{bucket['del_5xx']}")
        if len(bucket["rd_5xx"]) >= 2:
            if not alive():
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(storm) {len(bucket['rd_5xx'])} x 5xx on GET /cluster reads during "
                f"the removal storm (200 expected; service alive per /healthz) — "
                f"Type3_RuntimeFailure — samples: {bucket['rd_5xx'][:3]}"
            )
        elif bucket["rd_5xx"]:
            print(f"OBSERVATION (inconclusive, <2 occurrences): rd_5xx: "
                  f"{bucket['rd_5xx']}")
        if len(bucket["rd_flap"]) >= 2:
            DEFECTS.append(
                f"(storm) {len(bucket['rd_flap'])} x membership-flap reads: peers "
                f"set changed while no removal was accepted — "
                f"Type4_StateLogicViolation — samples: {bucket['rd_flap'][:3]}"
            )
        elif bucket["rd_flap"]:
            print(f"OBSERVATION (inconclusive, <2 occurrences): rd_flap: "
                  f"{bucket['rd_flap']}")
        if bucket["rd_other"]:
            print(f"OBSERVATION: non-200/5xx cluster-status dispositions during "
                  f"storm (recorded, not judged): {bucket['rd_other'][:3]}")
        if bucket["del_transport"] or bucket["rd_transport"]:
            print(f"ENV_ISSUES: transport during storm: "
                  f"{(bucket['del_transport'] + bucket['rd_transport'])[:3]}")
            if not alive():
                return "SCRIPT_ERROR"

        # ---- final state: cluster + data plane ----
        s1, peers1, _self1, raw1 = cluster_snapshot()
        print(f"[final GET /cluster] status={s1} "
              f"peers={sorted(peers1) if peers1 is not None else None} raw={raw1[:200]}")
        if s1 == 0:
            if not alive():
                return "SCRIPT_ERROR"
            print("ENV_ISSUE: transport failure on final snapshot; liveness ok")
        elif 500 <= s1 <= 599:
            if not alive():
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(final) GET /cluster after the storm returned {s1} (200 expected; "
                f"service alive per /healthz) — Type3_RuntimeFailure — "
                f"raw={raw1[:200]}"
            )
        elif s1 == 200 and peers0 is not None and peers1 is not None \
                and peers1 != peers0:
            DEFECTS.append(
                f"(final) peers set changed across the storm although every removal "
                f"was refused: before={sorted(peers0)} after={sorted(peers1)} — "
                f"Type4_StateLogicViolation"
            )
        if base_count is not None:
            time.sleep(0.5)
            final_count = exact_count(C)
            print(f"[final] exact count of {C} = {final_count} (expect {N_POINTS})")
            if final_count is None:
                print("ENV_ISSUE: final count unreadable — data-plane check skipped")
            elif final_count != N_POINTS:
                DEFECTS.append(
                    f"(final) data plane corrupted by the cluster-membership storm: "
                    f"exact count {final_count} != {N_POINTS} — "
                    f"Type4_StateLogicViolation"
                )

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
