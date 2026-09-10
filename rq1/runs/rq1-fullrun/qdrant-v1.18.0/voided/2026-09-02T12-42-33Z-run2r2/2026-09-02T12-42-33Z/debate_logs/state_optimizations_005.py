#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_optimizations_005
# strategy: lifecycle_concurrency
# endpoint: collections+optimizations
# constraint_ids: qdrant_behavioral_collections_optimizations_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-optimizations
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 7 (lifecycle concurrency) against the NAME-KEYED
  optimizer-status face (collections+optimizations). The assertion
  pins a two-branch state channel: existing -> 200 + per-shard
  optimizer status; missing -> 404. While one thread churns the
  collection lifecycle of a single name (create -> drop -> recreate,
  ending ABSENT after a confirmed final drop), 2 reader threads hammer
  GET optimizations on THAT name. During the churn the face must
  answer only the two legal branches — 200 while an incarnation
  exists, 404 while the name is absent:
    - a 500/5xx mid-churn = the server cannot gracefully express
      "temporarily absent/being recreated" (the reference qdrant
      defect shape: 500 instead of the graceful 404/200 pair);
    - a 200 on the never-yet-created name or AFTER the final confirmed
      drop = zombie incarnation readout (drop did not retire the
      status face);
    - a 200 body with a spec-typed-envelope conflict = corrupted
      readout serialization while the collection is being rebuilt.
  After the churn ends (final drop confirmed 200), repeated readouts
  must settle on 404 — a lingering 200 = residual state.
  Strategy-7 sporadic guard: 5xx/non-200/transport blips need >= 2
  occurrences with /healthz alive to be judged Type3 (1 = OBSERVATION).
  Shape oracle per materialized response_shape (result object;
  summary object w/ integer counters; running array; queued/
  completed/idle_segments array|null; conflict zones measured-only).
  # Blindspot: BS-03 Concurrency State Blindness
  Threads via threading module; reader count from
  TESTVDB_CONCURRENT_THREADS (default 10, clamped 2..10) capped at 2.
  [chunk_collections+optimizations coverage: lifecycle_concurrency x
   qdrant_behavioral_collections_optimizations_001 (same-name
   create/drop churn racing the 200/404 status channel)]
Oracle: during same-name lifecycle churn every GET optimizations
  returns exactly 200 or 404 (>= 2 occurrences of 5xx/non-200/
  transport with /healthz alive = Type3_RuntimeFailure if 5xx-majority
  else Type4_StateLogicViolation; exactly 1 = OBSERVATION); any 200
  body breaking the spec-typed envelope = Type4 shape conflict; after
  the final confirmed drop the face settles on 404 across repeated
  polls (a lingering 200 = Type4_StateLogicViolation zombie readout).
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
CHURN_CYCLES = 8


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


def triage_200(raw):
    """Returns (defect_note_or_None, measured_notes). None = envelope ok."""
    notes = []
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return "200 body is not JSON", notes
    if not isinstance(b, dict):
        return "200 body is not an object", notes
    res = b.get("result")
    if not isinstance(res, dict):
        return "result is not an object", notes
    for k in res:
        if k not in GROUPS:
            notes.append(f"extra result key {k!r}")
    v = res.get("summary")
    if v is not None and not isinstance(v, dict):
        return "summary not an object", notes
    v = res.get("running")
    if v is not None and not isinstance(v, list):
        return "running not an array", notes
    for k in ("queued", "completed", "idle_segments"):
        v = res.get(k)
        if v is not None and not isinstance(v, list):
            return f"{k} not array|null", notes
    summ = res.get("summary")
    if isinstance(summ, dict):
        for f in SUMMARY_INTS:
            fv = summ.get(f)
            if fv is not None and (not isinstance(fv, int)
                                   or isinstance(fv, bool)):
                return f"summary.{f} not an integer", notes
    return None, notes


def main():
    try:
        n_threads = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10"))
    except (TypeError, ValueError):
        n_threads = 10
    n_readers = max(2, min(n_threads, 10))
    if n_readers > 2:
        n_readers = 2

    TS = f"{int(time.time())}_{os.getpid()}"
    Y = "sop5_" + TS + "_y"
    DEFECTS = []
    env_fail = []
    stats = {"calls": 0, "transport": 0, "s5xx": 0, "sother": 0,
             "s404": 0, "s200": 0, "shape": 0,
             "blip_raws": [], "shape_raws": []}
    lock = threading.Lock()
    stop_evt = threading.Event()


    def _rec(k, raw):
        with lock:
            stats[k] += 1
            if k in ("s5xx", "sother", "transport", "shape"):
                (stats["blip_raws"] if k != "shape"
                 else stats["shape_raws"]).append(f"{k} {str(raw)[:100]}")


    def churn():
        """create -> drop repeated; ends with a confirmed final drop."""
        try:
            for i in range(CHURN_CYCLES):
                s, raw = safe_request("PUT", "create_collection",
                                      {"vectors": {"size": DIM,
                                                   "distance": "Cosine"}},
                                      path_params={"name": Y},
                                      query_params={"timeout": "30"})
                print(f"[churn#{i} create {Y}] status={s}")
                if s not in (200, 201):
                    with lock:
                        env_fail.append(f"churn#{i}: create {s}: "
                                        f"{str(raw)[:120]}")
                time.sleep(0.05)
                s, raw = safe_request("DELETE", "drop_collection",
                                      path_params={"name": Y},
                                      query_params={"timeout": "30"})
                print(f"[churn#{i} drop {Y}] status={s}")
                if s not in (200, 404):  # 404 = already absent, still fine
                    with lock:
                        env_fail.append(f"churn#{i}: drop {s}: "
                                        f"{str(raw)[:120]}")
                time.sleep(0.05)
        except Exception as e:
            with lock:
                env_fail.append(f"churn: {e}")


    def reader(rid):
        while not stop_evt.is_set():
            try:
                s, raw = safe_request("GET", "collection_optimizations",
                                      path_params={"collection_name": Y},
                                      timeout=20)
            except Exception as e:
                with lock:
                    env_fail.append(f"reader{rid}: {e}")
                return
            stats["calls"] += 1
            if s == 0:
                _rec("transport", raw)
                continue
            if 500 <= s <= 599:
                _rec("s5xx", raw)
                continue
            if s == 404:
                stats["s404"] += 1
                continue
            if s == 200:
                note, notes = triage_200(raw)
                for n in notes:
                    print(f"[reader{rid}] measured: {n}")
                if note:
                    _rec("shape", f"{note} :: {str(raw)[:120]}")
                else:
                    stats["s200"] += 1
                continue
            _rec("sother", raw)
            time.sleep(0.03)


    def settle_poll(attempts=5, delay=0.5):
        """After the final confirmed drop, the face must settle on 404."""
        for i in range(attempts):
            s, raw = safe_request("GET", "collection_optimizations",
                                  path_params={"collection_name": Y})
            print(f"[settle#{i}] status={s} raw={str(raw)[:180]}")
            if s == 404:
                return True
            if s == 0:
                if liveness("settle"):
                    return None
                return None
            if 500 <= s <= 599:
                if liveness("settle"):
                    DEFECTS.append(f"settle#{i}: post-churn readout returned "
                                   f"{s} — Type3_RuntimeFailure — "
                                   f"raw={str(raw)[:150]}")
                return None
            if s == 200:
                DEFECTS.append(f"settle#{i}: optimizations returned 200 for "
                               f"the name AFTER the final confirmed drop — "
                               f"zombie readout, delete did not retire the "
                               f"status face — Type4_StateLogicViolation — "
                               f"raw={str(raw)[:150]}")
                return None
            DEFECTS.append(f"settle#{i}: post-churn readout returned {s} — "
                           f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
            return None
        DEFECTS.append("settle: readout never settled on 404 within "
                       f"{attempts} attempts — Type4_StateLogicViolation")
        return None


    try:
        t_lc = threading.Thread(target=churn)
        readers = [threading.Thread(target=reader, args=(i,))
                   for i in range(1, n_readers + 1)]
        all_t = readers + [t_lc]
        for t in all_t:
            t.start()
        t_lc.join(timeout=180)
        stop_evt.set()
        for t in readers:
            t.join(timeout=30)

        still = [i for i, t in enumerate(all_t) if t.is_alive()]
        if still:
            print(f"ENV_FAIL: threads still alive after join timeouts: {still}")
            return "SCRIPT_ERROR"

        print(f"[stats] calls={stats['calls']} 200={stats['s200']} "
              f"404={stats['s404']} 5xx={stats['s5xx']} "
              f"other={stats['sother']} transport={stats['transport']} "
              f"shape={stats['shape']}")
        if stats["blip_raws"]:
            print(f"[stats.blips] {stats['blip_raws'][:5]}")
        if stats["shape_raws"]:
            print(f"[stats.shape] {stats['shape_raws'][:3]}")

        if env_fail:
            for f in env_fail:
                print(f"ENV_FAIL: {f}")
            return "SCRIPT_ERROR"

        # ---- typed judgement of the churn window ----
        blips = stats["transport"] + stats["s5xx"] + stats["sother"]
        if blips:
            if liveness("window"):
                if blips >= 2:
                    kind = ("Type3_RuntimeFailure" if stats["s5xx"] >= 2
                            else "Type4_StateLogicViolation")
                    DEFECTS.append(f"optimizations face took "
                                   f"{stats['s5xx']} 5xx / "
                                   f"{stats['sother']} other-non200 / "
                                   f"{stats['transport']} transport blips "
                                   f"during same-name lifecycle churn with "
                                   f"/healthz alive — {kind} — "
                                   f"raws={stats['blip_raws'][:3]}")
                else:
                    print("OBSERVATION: single face blip during churn (below "
                          "the >=2 strategy-7 sporadic guard) — not judged "
                          "a defect")
            else:
                return "SCRIPT_ERROR"
        if stats["shape"] >= 1:
            DEFECTS.append(f"{stats['shape']} churn-window 200 responses "
                           f"broke the spec-typed envelope — "
                           f"Type4_StateLogicViolation (spec wins) — "
                           f"raws={stats['shape_raws'][:3]}")

        # ---- settle: final state must be 404 ----
        r = settle_poll()
        if r is None:
            # a defect may already have been recorded; a transport/setup
            # abort without defect must be env-class
            if not DEFECTS:
                return "SCRIPT_ERROR"

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
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
