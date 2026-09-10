#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_optimizations_004
# strategy: concurrent
# endpoint: collections+optimizations
# constraint_ids: qdrant_behavioral_collections_optimizations_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-optimizations
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 4 (concurrent point-level operations racing the
  readout channel) against qdrant_behavioral_collections_optimizations_001:
  while N writer threads upsert disjoint point batches (wait=true) into
  ONE live collection, 2 reader threads hammer GET optimizations on it.
  The assertion pins "200 optimizer status per shard" for an existing
  collection with no timing caveat — concurrent writes are a normal
  load the status face must survive:
    - readers must observe ONLY HTTP 200 + spec-typed result envelope
      (a 404 mid-run = the face momentarily reported the live
      collection missing; a 5xx = the face crashed under write load);
    - every writer upsert must ack 200/201 (write integrity gate);
    - after all threads join, the queue accounting must drain to idle
      (3 consecutive reads, summary.queued_points == 0 and
      queued_optimizations == 0, 60s budget) and the describe
      points_count anchor must equal the total acked points — a
      shortfall = lost writes under concurrency, a surplus =
      duplicated writes, either way state did not reconcile.
  Envelope shape oracle per the materialized response_shape (result
  object; summary object with integer counters; running array;
  queued/completed/idle_segments array|null) — present groups must
  carry spec types; unknown/absent optional keys measured-only.
  # Blindspot: BS-03 Concurrency State Blindness
  Threads via threading module; count from TESTVDB_CONCURRENT_THREADS
  (default 10; writers clamped 2..10, plus 2 readers).
  [chunk_collections+optimizations coverage: concurrent x
   qdrant_behavioral_collections_optimizations_001 (readout channel
   integrity + write reconciliation under concurrent bulk upserts)]
Oracle: during concurrent wait=true writers every GET optimizations on
  the live collection returns 200 with the spec-typed result envelope
  (>= 2 5xx/non-200/transport blips with /healthz alive =
  Type3_RuntimeFailure if 5xx-majority else Type4_StateLogicViolation;
  exactly 1 = OBSERVATION); after join the queue drains to idle within
  60s and describe points_count == total acked points (mismatch =
  Type4_StateLogicViolation); 5xx = Type3 only with liveness.
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

# optimizations endpoint is not in the runtime PATHS whitelist — register
# it VERBATIM from raw_knowledge api_endpoints[].url:
#   {"path": "collections+optimizations", "method": "GET",
#    "url": "/collections/{collection_name}/optimizations"}
rt.PATHS["collection_optimizations"] = "/collections/{collection_name}/optimizations"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if 'optimizations' in k]}")
if rt.PATHS.get("collection_optimizations") != "/collections/{collection_name}/optimizations":
    print("VERDICT: SCRIPT_ERROR - optimizations URL registration failed")
    sys.exit(2)

DIM = 4
PTS_PER_BATCH = 25


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
    print(f"[liveness {tag}] healthz probe required")
    _hs, _hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={_hs} raw={str(_hraw)[:120]}")
    return _hs == 200


GROUPS = {"summary", "running", "queued", "completed", "idle_segments"}
SUMMARY_INTS = ("queued_optimizations", "queued_segments",
                "queued_points", "idle_segments")


def read_status(name, tag):
    """Returns (kind, payload): ok payload = (raw, result_dict)."""
    s, raw = safe_request("GET", "collection_optimizations",
                          path_params={"collection_name": name})
    if s == 0:
        return "transport", raw
    if s != 200:
        return "non200", (s, raw)
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return "shape", f"non-JSON 200 body: {str(raw)[:120]}"
    res = b.get("result") if isinstance(b, dict) else None
    if not isinstance(res, dict):
        return "shape", f"result not an object: {str(raw)[:150]}"
    v = res.get("summary")
    if v is not None and not isinstance(v, dict):
        return "shape", f"summary not an object: {v!r}"
    v = res.get("running")
    if v is not None and not isinstance(v, list):
        return "shape", f"running not an array: {v!r}"
    for k in ("queued", "completed", "idle_segments"):
        v = res.get(k)
        if v is not None and not isinstance(v, list):
            return "shape", f"{k} not array|null: {v!r}"
    summ = res.get("summary")
    if isinstance(summ, dict):
        for f in SUMMARY_INTS:
            fv = summ.get(f)
            if fv is not None and (not isinstance(fv, int)
                                   or isinstance(fv, bool)):
                return "shape", f"summary.{f} not an integer: {fv!r}"
    return "ok", (raw, res)


def is_idle(res):
    summ = res.get("summary") if isinstance(res, dict) else None
    if not isinstance(summ, dict):
        return None
    qo = summ.get("queued_optimizations")
    qp = summ.get("queued_points")
    if (not isinstance(qo, int) or isinstance(qo, bool)
            or not isinstance(qp, int) or isinstance(qp, bool)):
        return None
    running = res.get("running")
    run_empty = (running is None) or (isinstance(running, list)
                                      and len(running) == 0)
    return qo == 0 and qp == 0 and run_empty


def main():
    try:
        n_threads = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10"))
    except (TypeError, ValueError):
        n_threads = 10
    n_writers = max(2, min(n_threads, 10))

    TS = f"{int(time.time())}_{os.getpid()}"
    C = "sop4_" + TS + "_col"
    TOTAL = n_writers * PTS_PER_BATCH
    DEFECTS = []
    env_fail = []
    stats = {"calls": 0, "transport": 0, "s5xx": 0, "snon404": 0,
             "s404": 0, "shape": 0, "raws": []}
    stop_evt = threading.Event()
    wlock = threading.Lock()

    def writer(wid):
        base = wid * PTS_PER_BATCH
        pts = [{"id": base + i,
                "vector": [float((base + i) % 7) / 7.0, 0.2, 0.3, 0.4]}
               for i in range(PTS_PER_BATCH)]
        try:
            s, raw = safe_request("PUT", "upsert_points",
                                  path_params={"name": C},
                                  body={"points": pts},
                                  query_params={"wait": "true"},
                                  timeout=60)
            print(f"[writer{wid}] upsert status={s} raw={str(raw)[:120]}")
            if s not in (200, 201):
                with wlock:
                    env_fail.append(f"writer{wid}: upsert returned {s}: "
                                    f"{str(raw)[:120]}")
        except Exception as e:
            with wlock:
                env_fail.append(f"writer{wid}: {e}")

    def reader(rid):
        while not stop_evt.is_set():
            kind, payload = read_status(C, f"reader{rid}")
            stats["calls"] += 1
            if kind == "transport":
                stats["transport"] += 1
                stats["raws"].append(f"transport {str(payload)[:100]}")
            elif kind == "non200":
                s, raw = payload
                if 500 <= s <= 599:
                    stats["s5xx"] += 1
                elif s == 404:
                    stats["s404"] += 1
                else:
                    stats["snon404"] += 1
                stats["raws"].append(f"{s} {str(raw)[:100]}")
            elif kind == "shape":
                stats["shape"] += 1
                stats["raws"].append(f"shape {str(payload)[:100]}")
            time.sleep(0.05)

    def describe_points_count(name):
        s, raw = safe_request("GET", "describe_collection",
                              path_params={"name": name})
        if s != 200:
            return None, s, raw
        try:
            pc = json.loads(raw)["result"].get("points_count")
        except Exception:
            pc = None
        return pc, s, raw

    try:
        # ---- setup ----
        a_s, a_raw = safe_request("PUT", "create_collection",
                                  path_params={"name": C},
                                  body={"vectors": {"size": DIM,
                                                    "distance": "Cosine"}})
        print(f"[setup create] status={a_s} raw={a_raw[:150]}")
        if a_s not in (200, 201):
            print(f"SETUP_ERROR: create returned {a_s}")
            return "SCRIPT_ERROR"

        threads = []
        for i in range(n_writers):
            threads.append(threading.Thread(target=writer, args=(i,)))
        t_r1 = threading.Thread(target=reader, args=(1,))
        t_r2 = threading.Thread(target=reader, args=(2,))
        threads.extend([t_r1, t_r2])

        for t in threads:
            t.start()
        for t in threads:
            if t is not t_r1 and t is not t_r2:
                t.join(timeout=180)
        stop_evt.set()
        t_r1.join(timeout=30)
        t_r2.join(timeout=30)

        still = [i for i, t in enumerate(threads) if t.is_alive()]
        if still:
            print(f"ENV_FAIL: threads still alive after join timeouts: {still}")
            return "SCRIPT_ERROR"

        print(f"[stats] calls={stats['calls']} transport={stats['transport']} "
              f"5xx={stats['s5xx']} 404={stats['s404']} "
              f"other-non200={stats['snon404']} shape={stats['shape']}")
        if stats["raws"]:
            print(f"[stats.raws] {stats['raws'][:6]}")

        if env_fail:
            for f in env_fail:
                print(f"ENV_FAIL: {f}")
            return "SCRIPT_ERROR"

        # ---- readout channel judgement during concurrent writes ----
        blips = stats["transport"] + stats["s5xx"] + stats["snon404"]
        if blips:
            if liveness("channel"):
                if blips >= 2 or stats["s5xx"] >= 1:
                    kind = ("Type3_RuntimeFailure" if stats["s5xx"] >= 1
                            else "Type4_StateLogicViolation")
                    DEFECTS.append(f"readout channel took {stats['s5xx']} 5xx / "
                                   f"{stats['snon404']} other-non200 / "
                                   f"{stats['transport']} transport blips "
                                   f"under concurrent writers with /healthz "
                                   f"alive — {kind} — "
                                   f"raws={stats['raws'][:3]}")
                else:
                    print("OBSERVATION: single readout blip during concurrent "
                          "writes (below sporadic guard) — not judged a defect")
            else:
                return "SCRIPT_ERROR"
        if stats["s404"] >= 1:
            DEFECTS.append(f"{stats['s404']} readouts returned 404 for the "
                           f"LIVE collection under concurrent writes — "
                           f"Type4_StateLogicViolation (status face reported "
                           f"the collection missing) — raws={stats['raws'][:3]}")
        if stats["shape"] >= 1:
            DEFECTS.append(f"{stats['shape']} readouts returned 200 with a "
                           f"shape conflict — Type4_StateLogicViolation "
                           f"(spec wins) — raws={stats['raws'][:3]}")

        # ---- reconciliation: drain to idle, then count anchor ----
        deadline = time.time() + 60.0
        consec = 0
        drained = False
        while time.time() < deadline:
            kind, payload = read_status(C, "recon drain")
            if kind == "transport":
                liveness("recon")
                return "SCRIPT_ERROR"
            if kind == "non200":
                s, raw = payload
                if liveness("recon"):
                    DEFECTS.append(f"recon readout returned {s} after join — "
                                   f"{'Type3_RuntimeFailure' if 500 <= s <= 599 else 'Type4_StateLogicViolation'} "
                                   f"— raw={str(raw)[:150]}")
                else:
                    return "SCRIPT_ERROR"
                break
            if kind == "shape":
                DEFECTS.append(f"recon 200 body shape conflict: {payload} — "
                               f"Type4_StateLogicViolation")
                break
            _raw, res = payload
            idle = is_idle(res)
            if idle is None:
                consec = 0
            elif idle:
                consec += 1
                if consec >= 3:
                    drained = True
                    break
            else:
                consec = 0
            time.sleep(1.0)
        if not drained:
            if liveness("recon"):
                DEFECTS.append("queue accounting never drained to idle "
                               "within 60s after all writers joined — "
                               "Type4_StateLogicViolation")
            else:
                return "SCRIPT_ERROR"

        pc, ps, praw = describe_points_count(C)
        print(f"[recon describe] status={ps} points_count={pc} "
              f"raw={str(praw)[:200]}")
        if ps != 200:
            print(f"ENV_FAIL: describe returned {ps} after join")
            return "SCRIPT_ERROR"
        if pc is None:
            print("[recon] measured: points_count null/absent — anchor not "
                  "judged")
        elif isinstance(pc, bool) or not isinstance(pc, int):
            DEFECTS.append(f"(recon) points_count={pc!r} not an integer — "
                           f"Type4_StateLogicViolation")
        elif pc != TOTAL:
            DEFECTS.append(f"(recon) after {n_writers} concurrent writers "
                           f"acked {TOTAL} points, points_count={pc} — "
                           f"lost or duplicated writes — "
                           f"Type4_StateLogicViolation")

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
    try:
        _v = main()
    except Exception:
        import traceback
        traceback.print_exc()
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
