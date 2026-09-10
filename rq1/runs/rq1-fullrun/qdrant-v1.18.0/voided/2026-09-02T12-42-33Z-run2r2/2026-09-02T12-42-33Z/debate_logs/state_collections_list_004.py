#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_list_004
# strategy: concurrent
# endpoint: collections+list
# constraint_ids: qdrant_behavioral_collections_list_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collections
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 7 (lifecycle concurrency) against the global LIST
  face (collections+list; runtime PATHS list_collections =
  /collections, verbatim raw_knowledge api_endpoints[].url).
  qdrant_behavioral_collections_list_001 pins an UNCONDITIONAL face:
  GET /collections must always answer 200 with the
  result.collections[] envelope of {name} entries -- it takes no
  collection name, so no "temporarily absent collection" excuse
  exists for a 500/4xx while the registry churns. Strategy 4 vs 7:
  this is collection-level lifecycle (create/drop of the registry
  itself) racing the list readout, not point-level concurrency.
  # Blindspot: BS-03 Concurrency State Blindness
  Layout (threads via threading module, count from
  TESTVDB_CONCURRENT_THREADS, default 10, clamped 2..10):
    - N creator threads: each creates ONE uniquely-prefixed
      collection (concurrent registry growth).
    - 1 lifecycle thread: cycles create->drop of one prefixed name
      (ends absent) -- drop/create races against in-flight lists.
    - 2 lister threads: hammer GET /collections until stopped; every
      response is triaged (200/envelope/name-field).
  Judgement (G5-typed + strategy-7 sporadic guard):
    - malformed envelope on a 200 list (result.collections not an
      array / entries without a string name) >= 1 -> Type4
      (registry serialization corrupted mid-churn).
    - 5xx / non-200 / transport-blip on the list face: >= 2
      occurrences (with /healthz alive) -> Type3; exactly 1 ->
      OBSERVATION (race false-positive guard per strategy 7).
    - convergence after joins: all N created names present exactly
      once, churned name absent (bounded retries) -> else Type4.
  Global-face discipline: membership PREFIX-FILTERED (siblings
  tolerated); envelope shape judged on all entries.
  [chunk_collections+list coverage: concurrent x
   qdrant_behavioral_collections_list_001 (lifecycle create/drop
   churn vs concurrent list reads + post-churn convergence)]
Oracle: during concurrent prefixed creates + create/drop churn every
  GET /collections answers 200 with result.collections a JSON array
  of {name} entries (malformed 200 envelope = Type4 immediately);
  5xx/non-200/transport blips on the list face occur < 2 times with
  /healthz alive (>= 2 = Type3_RuntimeFailure); after all threads
  join the list converges to all N creator names present exactly
  once and the churned name absent (missing/duplicate/zombie =
  Type4_StateLogicViolation).
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

DIM = 4
CHURN_CYCLES = 6


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def parse_json(raw):
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return b if isinstance(b, dict) else None


def alive():
    _hs, _hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[healthz] status={_hs} raw={str(_hraw)[:120]}")
    return _hs == 200


def main():
    try:
        n_threads = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10"))
    except (TypeError, ValueError):
        n_threads = 10
    n_creators = max(2, min(n_threads, 10))

    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scl4_" + TS + "_"
    CREATOR_NAMES = [PFX + f"z{i}" for i in range(n_creators)]
    Y = PFX + "y"
    DEFECTS = []

    stats = {"calls": 0, "transport": 0, "s5xx": 0, "sother": 0,
             "malformed": 0, "noname": 0,
             "s5xx_raws": [], "sother_raws": [], "malformed_raws": []}
    env_fail = []
    stop_evt = threading.Event()

    def creator(idx, name):
        try:
            ok, err = rt.setup_default(name, DIM, "Cosine")
            if not ok:
                env_fail.append(f"creator{idx}: create {name} failed: {err}")
        except Exception as e:
            env_fail.append(f"creator{idx}: {e}")

    def lifecycle():
        """Churn one prefixed name: create -> drop, repeated. Ends absent."""
        try:
            for i in range(CHURN_CYCLES):
                s, raw = safe_request("PUT", "create_collection",
                                      {"vectors": {"size": DIM,
                                                   "distance": "Cosine"}},
                                      path_params={"name": Y},
                                      query_params={"timeout": "30"})
                print(f"[churn#{i} create {Y}] status={s}")
                if s == 0:
                    env_fail.append(f"lifecycle: create transport fail: {raw}")
                time.sleep(0.05)
                s, raw = safe_request("DELETE", "drop_collection",
                                      path_params={"name": Y},
                                      query_params={"timeout": "30"})
                print(f"[churn#{i} drop {Y}] status={s}")
                if s == 0:
                    env_fail.append(f"lifecycle: drop transport fail: {raw}")
                time.sleep(0.05)
        except Exception as e:
            env_fail.append(f"lifecycle: {e}")

    def lister(tid):
        while not stop_evt.is_set():
            try:
                s, raw = safe_request("GET", "list_collections", timeout=20)
            except Exception as e:
                env_fail.append(f"lister{tid}: {e}")
                return
            stats["calls"] += 1
            if s == 0:
                stats["transport"] += 1
                continue
            if 500 <= s <= 599:
                stats["s5xx"] += 1
                stats["s5xx_raws"].append(f"{s} {str(raw)[:100]}")
                continue
            if s != 200:
                stats["sother"] += 1
                stats["sother_raws"].append(f"{s} {str(raw)[:100]}")
                continue
            b = parse_json(raw)
            res = b.get("result") if isinstance(b, dict) else None
            cols = res.get("collections") if isinstance(res, dict) else None
            if not isinstance(cols, list):
                stats["malformed"] += 1
                stats["malformed_raws"].append(str(raw)[:120])
                continue
            for e in cols:
                if not (isinstance(e, dict)
                        and isinstance(e.get("name"), str) and e["name"]):
                    stats["noname"] += 1
            time.sleep(0.05)

    def list_until(tag, pred, attempts=4, delay=0.5):
        names = None
        for i in range(attempts):
            s, raw = safe_request("GET", "list_collections")
            print(f"[list#{tag}.{i}] status={s} raw={str(raw)[:240]}")
            if s == 0:
                alive()
                return "ERR", None
            if 500 <= s <= 599 or s != 200:
                if alive():
                    DEFECTS.append(f"list#{tag}.{i} returned {s} with service "
                                   f"alive — "
                                   f"{'Type3_RuntimeFailure' if 500 <= s <= 599 else 'Type4_StateLogicViolation'} "
                                   f"— raw={str(raw)[:150]}")
                else:
                    return "ERR", None
                return "NO", None
            b = parse_json(raw)
            res = b.get("result") if isinstance(b, dict) else None
            cols = res.get("collections") if isinstance(res, dict) else None
            if not isinstance(cols, list):
                DEFECTS.append(f"list#{tag}.{i} 200 body lacks "
                               f"result.collections array — "
                               f"Type4_StateLogicViolation — "
                               f"raw={str(raw)[:200]}")
                return "NO", None
            names = [e["name"] for e in cols
                     if isinstance(e, dict) and isinstance(e.get("name"), str)
                     and e["name"]]
            if pred(names):
                return "OK", names
            if i < attempts - 1:
                time.sleep(delay)
        return "NO", names

    try:
        threads = []
        t_l1 = threading.Thread(target=lister, args=(1,))
        t_l2 = threading.Thread(target=lister, args=(2,))
        t_lc = threading.Thread(target=lifecycle)
        threads.extend([t_l1, t_l2, t_lc])
        for i, n in enumerate(CREATOR_NAMES):
            threads.append(threading.Thread(target=creator, args=(i, n)))

        for t in threads:
            t.start()
        for t in threads:
            if t is not t_l1 and t is not t_l2:
                t.join(timeout=120)
        stop_evt.set()
        t_l1.join(timeout=30)
        t_l2.join(timeout=30)

        still_running = [i for i, t in enumerate(threads) if t.is_alive()]
        if still_running:
            print(f"ENV_FAIL: threads still alive after join timeouts: "
                  f"{still_running} (cannot judge convergence)")
            return "SCRIPT_ERROR"

        print(f"[stats] calls={stats['calls']} transport={stats['transport']} "
              f"5xx={stats['s5xx']} non200={stats['sother']} "
              f"malformed200={stats['malformed']} noname={stats['noname']}")
        if stats["s5xx_raws"]:
            print(f"[stats.5xx] {stats['s5xx_raws'][:5]}")
        if stats["sother_raws"]:
            print(f"[stats.non200] {stats['sother_raws'][:5]}")
        if stats["malformed_raws"]:
            print(f"[stats.malformed] {stats['malformed_raws'][:5]}")

        if env_fail:
            for f in env_fail:
                print(f"ENV_FAIL: {f}")
            return "SCRIPT_ERROR"

        # ---- typed judgement of the concurrent window ----
        blips = stats["s5xx"] + stats["sother"] + stats["transport"]
        if blips:
            if alive():
                if blips >= 2:
                    kind = ("Type3_RuntimeFailure" if stats["s5xx"] >= 2
                            else "Type4_StateLogicViolation")
                    DEFECTS.append(f"list face took {stats['s5xx']} 5xx / "
                                   f"{stats['sother']} non-200 / "
                                   f"{stats['transport']} transport blips "
                                   f"during lifecycle churn with /healthz "
                                   f"alive — {kind} — raws: "
                                   f"{(stats['s5xx_raws'] + stats['sother_raws'])[:3]}")
                else:
                    print("OBSERVATION: single list-face blip during churn "
                          "(below the >=2 strategy-7 sporadic guard) — "
                          "not judged a defect")
            else:
                return "SCRIPT_ERROR"
        if stats["malformed"] >= 1:
            DEFECTS.append(f"{stats['malformed']} list responses returned 200 "
                           f"but broke the pinned result.collections[] "
                           f"envelope mid-churn — Type4_StateLogicViolation "
                           f"— raws={stats['malformed_raws'][:3]} "
                           f"(qdrant_behavioral_collections_list_001)")
        if stats["noname"] >= 1:
            DEFECTS.append(f"{stats['noname']} entries lacked a string name "
                           f"field mid-churn — Type4_StateLogicViolation")

        # ---- convergence: creators' names present exactly once, Y absent ----
        st, names = list_until(
            "conv",
            lambda ns: all(n in ns for n in CREATOR_NAMES)
            and all(ns.count(n) == 1 for n in CREATOR_NAMES)
            and Y not in ns)
        if st == "ERR":
            return "SCRIPT_ERROR"
        if st == "NO":
            ns = names or []
            miss = [n for n in CREATOR_NAMES if n not in ns]
            dup = [n for n in CREATOR_NAMES if ns.count(n) > 1]
            parts = []
            if miss:
                parts.append(f"missing after successful creates: {miss}")
            if dup:
                parts.append(f"duplicated entries: {dup}")
            if Y in ns:
                parts.append(f"churned name {Y} present after final drop")
            DEFECTS.append("; ".join(parts) + " — "
                           "Type4_StateLogicViolation (registry diverged "
                           "after concurrent lifecycle churn)")

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        for n in CREATOR_NAMES:
            try:
                rt.drop_collection(n)
            except Exception:
                pass
        try:
            rt.drop_collection(Y)
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
