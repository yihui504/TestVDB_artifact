#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_cluster_recover_003
# strategy: concurrent
# endpoint: cluster+recover
# constraint_ids: qdrant_state_cluster_recover_001, qdrant_behavioral_cluster_recover_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/recover-current-peer
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 Concurrency State Blindness
"""
Attack: Strategy 4 (concurrent-operation attack) on POST /cluster/recover
  (URL from raw_knowledge api_endpoints[].url, registered into rt.PATHS).
  Blindspot BS-03 (concurrency state blindness — WAL/replay-era data loss
  under concurrent operational mutations) mapped to this chunk's face: writer
  threads upsert DISTINCT points with wait=true (durability promised per
  accepted call) while a recover thread fires the destructive
  metadata-removal op mid-storm. Every ACCEPTED (2xx, wait=true) write must be
  reflected in the final exact count — the state constraint
  qdrant_state_cluster_recover_001 says recover restarts "from local data",
  so losing an acknowledged write is Type4_StateLogicViolation; ghost extra
  points (count above seed+accepted, unique ids make double-count impossible
  on correct semantics) are likewise Type4. Writer 5xx events: >=2 distinct =
  Type3_RuntimeFailure only after /healthz liveness (single event = inconclusive
  observation, race false-positive guard per Strategy 7 key points); the
  recover call's own disposition is recorded (2xx/4xx both recordable; 5xx =
  Type3 after liveness; standalone "Distributed mode disabled" 4xx mask =
  OBSERVATION per the R6 lesson — the accepted-write-durability leg stays
  falsifiable either way because it only counts calls that WERE accepted).
  G6 mutation justification: the interleaving point (recover fired while
  wait=true upserts are in flight) is the maximal-timing window where a
  metadata wipe can race the WAL/durability path.
  [chunk_cluster+recover coverage: concurrent x
   qdrant_state_cluster_recover_001 (accepted-write durability across the
   destructive op) + qdrant_behavioral_cluster_recover_001 (disposition under
   concurrent load)]
Oracle: with WRITERS (env TESTVDB_CONCURRENT_THREADS, default 20, capped to
  10) threads each doing 4 sequential wait=true single-point upserts of
  globally unique ids, plus one mid-storm POST /cluster/recover: final exact
  count == 5 + total accepted 2xx upserts (less = acknowledged write lost =
  Type4_StateLogicViolation; more = ghost points = Type4_StateLogicViolation);
  every writer call disposition in {2xx, 4xx} with >=2 distinct 5xx events =
  Type3_RuntimeFailure only after /healthz returns 200 (single 5xx =
  observation); final GET /collections/{c} -> 200 (404 = Type4);
  /healthz 200 within the 20s grace window (never-200 = Type3).
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


def load_recover_template():
    """Standing lesson: URL only from raw_knowledge api_endpoints[].url."""
    for _p in Path(__file__).resolve().parents:
        _rk = _p / "raw_knowledge.json"
        if _rk.exists():
            try:
                for _e in json.loads(_rk.read_text(encoding="utf-8")).get("api_endpoints", []):
                    if _e.get("path") == "cluster+recover" and _e.get("url"):
                        return _e["url"]
            except Exception:
                return None
    return None


_RECOVER_TPL = load_recover_template()
if not _RECOVER_TPL:
    print("VERDICT: SCRIPT_ERROR - cluster+recover url not derivable from raw_knowledge api_endpoints[].url")
    sys.exit(2)
rt.PATHS["cluster_recover"] = _RECOVER_TPL
print(f"[url-derived] cluster+recover -> {_RECOVER_TPL} (raw_knowledge api_endpoints[].url)")


def safe_request(method, path_key, path_params=None, body=None, query_params=None,
                timeout=30):
    """All HTTP through the runtime; forwards timeout/path_params/body/
    query_params exactly as call sites use them (R6 lesson)."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


GRACE_S = 20
SEED = 5
BATCH = 4
THREADS_ENV = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "20"))
WRITERS = max(2, min(THREADS_ENV, 10))
DIM = 4


def exact_count(name):
    """POST count exact=true -> (status, count|None, raw); envelope result.<field>."""
    s, raw = safe_request("POST", "count", path_params={"name": name},
                          body={"exact": True})
    if s != 200:
        return s, None, raw
    try:
        b = json.loads(raw) if raw else {}
        node = b.get("result") if isinstance(b, dict) else None
        if isinstance(node, dict) and isinstance(node.get("count"), int):
            return s, node["count"], raw
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    return s, None, raw


def upsert_wait(name, points):
    """PUT upsert with wait=true (wait is a URL query param on qdrant)."""
    return safe_request("PUT", "upsert_points", path_params={"name": name},
                        body={"points": points}, query_params={"wait": "true"})


def grace_liveness(seconds):
    """Poll /healthz up to `seconds`; True once 200."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        hs, _hraw = safe_request("GET", "healthz")
        if hs == 200:
            return True
        time.sleep(1.0)
    return False


def liveness_ok():
    """Inline /healthz probe (exact call form kept visible)."""
    hs, hraw = safe_request("GET", "healthz")
    print(f"[healthz] probe status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "screc3_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []

    lock = threading.Lock()
    tally = {"accepted": 0, "rejected_4xx": 0, "err_5xx": 0, "transport": 0}
    thread_errors = []

    try:
        # ---- reachability probes ----
        if not liveness_ok():
            print("ENV_ISSUE: /healthz not 200 at probe — service not exercisable")
            return "SCRIPT_ERROR"
        cs0, craw0 = safe_request("GET", "cluster_status")
        print(f"[probe GET /cluster] status={cs0} raw={craw0[:200]}")
        if cs0 == 0 or 500 <= cs0 <= 599:
            print(f"ENV_ISSUE: GET /cluster returned {cs0} — cluster face not exercisable")
            return "SCRIPT_ERROR"

        # ---- setup: seed data plane ----
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR create {C}: {err}")
            return "SCRIPT_ERROR"
        pts = [{"id": i, "vector": [0.1 * (i + 1), 0.2, 0.3, 0.4],
                "payload": {"batch": "seed"}} for i in range(SEED)]
        s, raw = upsert_wait(C, pts)
        print(f"[seed upsert wait=true] status={s} raw={raw[:200]}")
        if s not in (200, 201):
            print(f"SETUP_ERROR seed upsert {s}: {raw[:200]}")
            return "SCRIPT_ERROR"
        sc, n0, craw_c = exact_count(C)
        print(f"[baseline exact count] status={sc} count={n0} raw={craw_c[:200]}")
        if sc != 200 or n0 != SEED:
            print(f"SETUP_ERROR baseline count status={sc} count={n0} (expected {SEED})")
            return "SCRIPT_ERROR"

        def writer(idx):
            try:
                for k in range(BATCH):
                    pid = 10000 + idx * 1000 + k
                    s, raw = upsert_wait(C, [{"id": pid,
                                              "vector": [0.05 * (k + 1), 0.6, 0.7, 0.8],
                                              "payload": {"writer": idx, "k": k}}])
                    with lock:
                        if 200 <= s < 300:
                            tally["accepted"] += 1
                        elif 400 <= s <= 499:
                            tally["rejected_4xx"] += 1
                        elif 500 <= s <= 599:
                            tally["err_5xx"] += 1
                            print(f"[writer {idx} upsert {pid}] 5xx status={s} raw={raw[:150]}")
                        elif s == 0:
                            tally["transport"] += 1
                            print(f"[writer {idx} upsert {pid}] transport raw={raw[:150]}")
                    time.sleep(0.01)
            except Exception as e:  # script-bug guard: never let a thread die silently
                with lock:
                    thread_errors.append(f"writer {idx}: {e!r}")

        def recover_fire():
            try:
                time.sleep(0.05)  # mid-storm interleave point (G6)
                s, raw = safe_request("POST", "cluster_recover")
                print(f"[mid-storm POST /cluster/recover] status={s} raw={raw[:300]}")
                if 500 <= s <= 599:
                    with lock:
                        DEFECTS.append(
                            f"mid-storm POST /cluster/recover returned {s} "
                            f"(5xx; liveness re-checked below) — "
                            f"Type3_RuntimeFailure — raw={raw[:200]}"
                        )
                elif 400 <= s <= 499 and "distributed" in str(raw).lower():
                    print("OBSERVATION (mask): recover refused 4xx with the "
                          "standalone distributed-mode gate — accepted-write "
                          "durability leg still judged")
            except Exception as e:
                with lock:
                    thread_errors.append(f"recover_fire: {e!r}")

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(WRITERS)]
        threads.append(threading.Thread(target=recover_fire))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        print(f"[tally] writers={WRITERS} batch={BATCH} accepted={tally['accepted']} "
              f"rejected_4xx={tally['rejected_4xx']} err_5xx={tally['err_5xx']} "
              f"transport={tally['transport']} thread_errors={thread_errors}")
        if thread_errors:
            print(f"ENV_ISSUE: worker thread exceptions (script-side): {thread_errors}")
            return "SCRIPT_ERROR"

        # ---- settle + liveness grace (accepted recover may restart consensus) ----
        time.sleep(2.0)
        if not grace_liveness(GRACE_S):
            DEFECTS.append(
                f"after the concurrent storm + recover /healthz never returned "
                f"200 within {GRACE_S}s — Type3_RuntimeFailure"
            )
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"

        # ---- writer-plane 5xx judgment (>=2 distinct = Type3) ----
        if tally["err_5xx"] >= 2:
            if not liveness_ok():
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"{tally['err_5xx']} writer upserts returned 5xx during the "
                f"recover interleave (service alive per /healthz) — "
                f"Type3_RuntimeFailure"
            )
        elif tally["err_5xx"] == 1:
            print("OBSERVATION: single writer 5xx during the race — "
                  "inconclusive per the race false-positive guard, recorded")

        # ---- durability: every accepted write must be present ----
        expected = SEED + tally["accepted"]
        sc2, n1, craw2 = exact_count(C)
        print(f"[final exact count] status={sc2} count={n1} expected={expected} "
              f"raw={craw2[:200]}")
        if sc2 == 200 and n1 is not None and n1 != expected:
            kind = ("acknowledged write lost" if n1 < expected else "ghost points above seed+accepted")
            DEFECTS.append(
                f"final exact count {n1} != expected {expected} (seed {SEED} + "
                f"accepted {tally['accepted']} wait=true upserts) — {kind} — "
                f"Type4_StateLogicViolation"
            )
        elif sc2 == 0 or 500 <= sc2 <= 599:
            if not liveness_ok():
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"final exact count returned {sc2} (200 expected; service "
                f"alive per /healthz) — Type3_RuntimeFailure — raw={craw2[:200]}"
            )

        ds, draw = safe_request("GET", "describe_collection", path_params={"name": C})
        print(f"[final describe] status={ds} raw={draw[:200]}")
        if ds == 404:
            DEFECTS.append(
                f"GET /collections/{C} returned 404 after the storm+recover — "
                f"collection state destroyed — Type4_StateLogicViolation"
            )
        elif ds == 0 or 500 <= ds <= 599:
            if not liveness_ok():
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"describe after storm+recover returned {ds} (200 expected; "
                f"service alive per /healthz) — Type3_RuntimeFailure — "
                f"raw={draw[:200]}"
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
