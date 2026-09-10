#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_exists_005
# strategy: concurrent
# endpoint: collections+exists
# constraint_ids: qdrant_behavioral_collections_exists_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/collection-exists
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (Concurrency State Blindness — access during
#   lifecycle churn of the SAME collection)
"""
Attack: lifecycle concurrency on ONE name x exists access storm
  (Strategy 7: collection-level create->delete->recreate churn while
  readers hammer the exists endpoint — the migration / blue-green
  redeploy pattern). Unlike state_collections_exists_004 (independent
  settled lifecycles), here the ground truth GENUINELY FLIPS mid-run:
  during the race BOTH exists=true and exists=false are legal answers
  (the state is truly changing), and only the CHANNEL is pinned —
  every single answer must be a well-formed HTTP 200 with a boolean
  result.exists. The assertion's "never 404" is unconditional, so a
  404 during churn is a direct violation at count>=1; 5xx is the
  classic graceful-degradation failure (should be a 200+body answer,
  never an internal error) judged Type3 only with /healthz liveness
  AND the strategy-7 reproduction rule (>=2 occurrences).
  After quiescence (final drop + describe control = 404) the readout
  must settle: exists == 200 + result.exists=false exactly.
  [chunk_collections+exists coverage: concurrent(lifecycle) x
   qdrant_behavioral_collections_exists_001 (churn-window channel
   integrity: never-404 / no 5xx / boolean shape; post-quiescence
   settled verdict)]
Oracle: during the churn window every exists answer is a well-formed
  200 with boolean result.exists (any 404 = Type4 at count>=1;
  >=2 x 5xx with /healthz alive = Type3_RuntimeFailure; a single 5xx
  is logged as an inconclusive observation); after the final
  200-confirmed delete and describe control = 404, exists answers
  exactly 200 + result.exists=false. Verdict flips between true/false
  DURING churn are legal and not judged.
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

# exists endpoint is not in the runtime PATHS whitelist — register it
# VERBATIM from raw_knowledge api_endpoints[].url:
#   {"path": "collections+exists", "method": "GET",
#    "url": "/collections/{collection_name}/exists"}
rt.PATHS["collection_exists"] = "/collections/{collection_name}/exists"
if rt.PATHS.get("collection_exists") != "/collections/{collection_name}/exists":
    print("VERDICT: SCRIPT_ERROR - exists URL registration failed")
    sys.exit(2)

N_THREADS = max(2, int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10")))
READERS = max(2, N_THREADS - 1)
N_CYCLES = max(3, int(os.environ.get("TESTVDB_EXISTS_LIFECYCLE_CYCLES", "8")))


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def parse_exists(raw):
    """Shape-checked readout per materialized response_shape
    (result: object, result.exists: boolean)."""
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return False, None, "non-JSON body"
    res = b.get("result") if isinstance(b, dict) else None
    if isinstance(res, bool):
        return False, res, "result is a bare bool (spec pins result.exists object shape)"
    if not isinstance(res, dict):
        return False, None, "result missing or not an object"
    ev = res.get("exists")
    if not isinstance(ev, bool):
        return False, None, "result.exists missing or not a boolean"
    return True, ev, ""


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sce5_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []
    lock = threading.Lock()
    stop_evt = threading.Event()
    never200 = []     # non-200 answers during churn (404 = pinned "never")
    five_xx = []      # 5xx / shape-malformed answers during churn
    transports = []   # status=0 during churn
    env_failures = []
    counts = {"ok": 0, "true": 0, "false": 0}

    def alive():
        _hs, _hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[healthz] status={_hs} raw={str(_hraw)[:120]}")
        return _hs == 200

    def lifecycle_thread():
        """Thread L: create -> drop cycles on the SAME name C."""
        for i in range(N_CYCLES):
            if stop_evt.is_set():
                return
            try:
                ok, err = rt.setup_default(C, 4, "Cosine")
                if not ok:
                    with lock:
                        env_failures.append(f"L#{i}: create not ok {str(err)[:100]}")
            except Exception as e:
                with lock:
                    env_failures.append(f"L#{i}: create exception {str(e)[:100]}")
            time.sleep(0.08)
            try:
                safe_request("DELETE", "drop_collection", path_params={"name": C})
            except Exception as e:
                with lock:
                    env_failures.append(f"L#{i}: drop exception {str(e)[:100]}")
            time.sleep(0.08)
        print("[L] lifecycle loop finished")

    def reader_thread(rid):
        """Reader: exists storm on C. Verdict value is unjudged during churn
        (state truly flips); only the channel + shape are pinned."""
        while not stop_evt.is_set():
            try:
                s, raw = safe_request("GET", "collection_exists",
                                      path_params={"collection_name": C})
            except Exception as e:
                with lock:
                    transports.append(f"R{rid}: exception {str(e)[:100]}")
                time.sleep(0.02)
                continue
            if s == 0:
                with lock:
                    transports.append(f"R{rid}: status=0 {str(raw)[:100]}")
            elif 500 <= s <= 599:
                with lock:
                    five_xx.append(f"R{rid}: {s} raw={str(raw)[:120]}")
            elif s != 200:
                with lock:
                    never200.append(f"R{rid}: {s} raw={str(raw)[:120]}")
            else:
                shape_ok, ev, note = parse_exists(raw)
                if not shape_ok:
                    with lock:
                        five_xx.append(f"R{rid}: 200 but malformed body ({note}) "
                                       f"raw={str(raw)[:120]}")
                else:
                    with lock:
                        counts["ok"] += 1
                        if ev:
                            counts["true"] += 1
                        else:
                            counts["false"] += 1
            time.sleep(0.02)

    try:
        # ---- race window ----
        threads = [threading.Thread(target=lifecycle_thread, daemon=True)]
        for rid in range(READERS):
            threads.append(threading.Thread(target=reader_thread, args=(rid,), daemon=True))
        for t in threads:
            t.start()
        for t in threads[:1]:
            t.join(timeout=180)
        # give readers a final beat inside the last churn phase, then stop
        time.sleep(0.5)
        stop_evt.set()
        for t in threads[1:]:
            t.join(timeout=30)
        still = [i for i, t in enumerate(threads) if t.is_alive()]
        if still:
            print(f"ENV_ISSUE: threads still alive after join: {still}")

        print(f"[churn stats] well-formed 200 answers: {counts['ok']} "
              f"(true={counts['true']}, false={counts['false']}); "
              f"non-200={len(never200)}; 5xx/malformed={len(five_xx)}; "
              f"transport={len(transports)}")

        # ---- quiescence: C must be verifiably gone ----
        gone = False
        for _ in range(20):
            try:
                s, _raw = safe_request("GET", "describe_collection", path_params={"name": C})
            except Exception:
                s = -1
            if s == 404:
                gone = True
                break
            time.sleep(0.5)
        if not gone:
            try:
                safe_request("DELETE", "drop_collection", path_params={"name": C})
            except Exception:
                pass
            time.sleep(1.0)
        print(f"[quiescence] describe({C}) -> 404? {gone}")

        # ---- settled verdict: exists == 200 + false ----
        s, raw = safe_request("GET", "collection_exists",
                              path_params={"collection_name": C})
        print(f"[settled exists] status={s} raw={str(raw)[:200]}")
        if s == 0:
            alive()
            return "SCRIPT_ERROR"
        if 500 <= s <= 599:
            if alive():
                DEFECTS.append(f"settled exists returned {s} with service alive after "
                               f"quiescence — Type3_RuntimeFailure — raw={str(raw)[:150]}")
            else:
                return "SCRIPT_ERROR"
        else:
            shape_ok, ev, note = parse_exists(raw)
            if s != 200:
                DEFECTS.append(f"settled exists returned {s} (pinned channel: 200 + "
                               f"body, never 404) — Type4_StateLogicViolation — "
                               f"raw={str(raw)[:150]} "
                               f"(qdrant_behavioral_collections_exists_001)")
            elif not shape_ok:
                DEFECTS.append(f"settled exists 200 body violates pinned shape "
                               f"result.exists:boolean ({note}) — "
                               f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
            elif ev is not False:
                DEFECTS.append(f"settled exists answered true after the final delete "
                               f"and a describe control of 404 — readout disagrees with "
                               f"control — Type4_StateLogicViolation "
                               f"(qdrant_behavioral_collections_exists_001)")

        # ---- churn-window adjudication ----
        # never-404 is unconditional in the assertion: count>=1 is a defect
        for n in never200:
            DEFECTS.append(f"churn window: exists answered non-200 ({n}) — the "
                           f"assertion pins existence to the body, never an HTTP "
                           f"error status — Type4_StateLogicViolation "
                           f"(qdrant_behavioral_collections_exists_001)")
        # 5xx / malformed: strategy-7 reproduction rule (>=2) + liveness
        if five_xx:
            if alive():
                if len(five_xx) >= 2:
                    DEFECTS.append(f"churn window: {len(five_xx)} x 5xx/malformed "
                                   f"answers on exists while the collection lifecycle "
                                   f"churned (graceful 200+body was expected) — "
                                   f"Type3_RuntimeFailure — samples: {five_xx[:3]}")
                else:
                    print(f"OBSERVATION (inconclusive, <2 occurrences): {five_xx}")
            else:
                return "SCRIPT_ERROR"
        if transports:
            if alive():
                if len(transports) >= 2:
                    DEFECTS.append(f"churn window: {len(transports)} x transport "
                                   f"failures on exists with service alive — "
                                   f"Type3_RuntimeFailure — samples: {transports[:3]}")
                else:
                    print(f"OBSERVATION (inconclusive, <2 occurrences): {transports}")
            else:
                return "SCRIPT_ERROR"
        if env_failures and not DEFECTS:
            print(f"ENV_ISSUES (not judged as defects): {env_failures[:5]}")
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
    try:
        _v = main()
    except Exception:
        import traceback
        traceback.print_exc()
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
