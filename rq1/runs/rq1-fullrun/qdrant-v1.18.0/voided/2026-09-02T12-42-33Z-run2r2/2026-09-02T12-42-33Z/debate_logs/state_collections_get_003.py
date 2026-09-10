#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_get_003
# strategy: concurrent
# endpoint: collections+get
# constraint_ids: qdrant_behavioral_collections_get_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (Concurrency State Blindness — describe access during
#   lifecycle churn of the SAME collection name)
"""
Attack: Strategy 7 (lifecycle concurrency) on the DESCRIBE face
  (collections+get; runtime PATHS describe_collection =
   /collections/{name}, verbatim raw_knowledge api_endpoints[].url).
  A lifecycle thread churns ONE name (create -> drop -> recreate) —
  the migration / blue-green redeploy pattern — while reader threads
  hammer GET describe. During the race the ground truth GENUINELY
  FLIPS, so BOTH 200 (full config) and 404 (with error message) are
  legal answers; what is pinned is the CHANNEL and the BODY:
  - a 200 must be well-formed per the assertion's full-config promise
    (result object with a status string and a config object holding a
    params object) — a malformed 200 is a Type4 shape violation at
    count>=1;
  - any 5xx is the classic graceful-degradation failure (should be a
    200-config or a 404 answer, never an internal error), judged
    Type3 only with /healthz liveness AND the strategy-7 reproduction
    rule (>=2 occurrences; a single occurrence is logged as an
    inconclusive observation).
  After quiescence (final drop + poll), the settled readout must be
  exactly 404 with an error message — a settled 200-with-config after
  a confirmed delete is ghost state (Type1).
  Distinct from state_collections_exists_005 (exists channel): the
  judged face here is the FULL CONFIG payload of describe.
  [chunk_collections+get coverage: concurrent(lifecycle churn) x
   qdrant_behavioral_collections_get_001 (churn-window channel
   integrity: 200-shape / no 5xx / settled 404 post-delete)]
Oracle: during the churn window every describe answer is either a
  well-formed 200 (result object + result.status string +
  result.config object + result.config.params object) or a 404 with a
  non-empty error message (malformed 200 = Type4 at count>=1; >=2 x
  5xx with /healthz alive = Type3_RuntimeFailure; a single 5xx is
  logged as an inconclusive observation); after the 200-confirmed
  final delete, describe answers exactly 404 with an error message —
  a settled 200-with-config = Type1_IllegalSuccess (ghost).
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

N_THREADS = max(2, int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10")))
READERS = max(2, N_THREADS - 1)
N_CYCLES = max(3, int(os.environ.get("TESTVDB_DESCRIBE_LIFECYCLE_CYCLES", "8")))


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def parse_200(raw):
    """Shape-checked readout of a 200 describe answer per the assertion's
    full-config promise (core subset, materialized response_shape)."""
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return False, "non-JSON body on a 200 answer"
    res = b.get("result") if isinstance(b, dict) else None
    if not isinstance(res, dict):
        return False, "result missing or not an object"
    if not isinstance(res.get("status"), str) or not res.get("status"):
        return False, "result.status missing or not a non-empty string"
    cfg = res.get("config")
    if not isinstance(cfg, dict):
        return False, "result.config missing or not an object"
    if not isinstance(cfg.get("params"), dict):
        return False, "result.config.params missing or not an object"
    return True, ""


def error_message_present(raw, name):
    b = None
    try:
        bb = json.loads(raw) if raw else None
        b = bb if isinstance(bb, dict) else None
    except (json.JSONDecodeError, ValueError, TypeError):
        b = None
    if isinstance(b, dict):
        err = b.get("error")
        if isinstance(err, str) and err.strip():
            return True
    return bool(str(raw or "").strip() and name in str(raw))


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scg3_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []
    lock = threading.Lock()
    stop_evt = threading.Event()
    malformed = []   # 200 answers violating the full-config shape (Type4)
    five_xx = []     # 5xx answers during churn (Type3, >=2 + liveness)
    bad_404 = []     # bare 404 without an error message (Type4)
    odd_4xx = []     # non-{200,404} answers during churn (Type4)
    transports = []  # status=0 / exceptions during churn
    env_failures = []
    counts = {"ok200": 0, "ok404": 0}

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
        """Reader: describe storm on C. Mid-churn BOTH 200 and 404 are
        legal; the channel and the body shape are what is pinned."""
        while not stop_evt.is_set():
            try:
                s, raw = safe_request("GET", "describe_collection",
                                      path_params={"name": C})
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
            elif s == 200:
                shape_ok, note = parse_200(raw)
                if shape_ok:
                    with lock:
                        counts["ok200"] += 1
                else:
                    with lock:
                        malformed.append(f"R{rid}: 200 but malformed ({note}) "
                                         f"raw={str(raw)[:120]}")
            elif s == 404:
                if error_message_present(raw, C):
                    with lock:
                        counts["ok404"] += 1
                else:
                    with lock:
                        bad_404.append(f"R{rid}: bare 404 without error message "
                                       f"raw={str(raw)[:120]}")
            else:
                with lock:
                    odd_4xx.append(f"R{rid}: {s} raw={str(raw)[:120]}")
            time.sleep(0.02)

    try:
        # ---- race window ----
        threads = [threading.Thread(target=lifecycle_thread, daemon=True)]
        for rid in range(READERS):
            threads.append(threading.Thread(target=reader_thread, args=(rid,),
                                            daemon=True))
        for t in threads:
            t.start()
        for t in threads[:1]:
            t.join(timeout=180)
        time.sleep(0.5)
        stop_evt.set()
        for t in threads[1:]:
            t.join(timeout=30)
        still = [i for i, t in enumerate(threads) if t.is_alive()]
        if still:
            print(f"ENV_ISSUE: threads still alive after join: {still}")

        print(f"[churn stats] well-formed 200={counts['ok200']}, "
              f"404-with-message={counts['ok404']}; malformed200={len(malformed)}; "
              f"5xx={len(five_xx)}; bare404={len(bad_404)}; "
              f"odd4xx={len(odd_4xx)}; transport={len(transports)}")

        # ---- quiescence: C must be verifiably gone ----
        gone = False
        for _ in range(20):
            try:
                s, _raw = safe_request("GET", "describe_collection",
                                       path_params={"name": C})
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

        # ---- settled verdict: exactly 404 + error message ----
        s, raw = safe_request("GET", "describe_collection", path_params={"name": C})
        print(f"[settled describe] status={s} raw={str(raw)[:240]}")
        if s == 0:
            alive()
            return "SCRIPT_ERROR"
        if 500 <= s <= 599:
            if alive():
                DEFECTS.append(f"settled describe returned {s} with service alive "
                               f"after quiescence — Type3_RuntimeFailure — "
                               f"raw={str(raw)[:150]}")
            else:
                return "SCRIPT_ERROR"
        elif s == 200:
            DEFECTS.append(f"settled describe returned 200 with config after the "
                           f"final delete and a 404 poll control — ghost state — "
                           f"Type1_IllegalSuccess — raw={str(raw)[:150]} "
                           f"(qdrant_behavioral_collections_get_001)")
        elif s != 404:
            if alive():
                DEFECTS.append(f"settled describe returned {s} (pinned: 404 with "
                               f"an error message) — Type4_StateLogicViolation — "
                               f"raw={str(raw)[:150]}")
            else:
                return "SCRIPT_ERROR"
        elif not error_message_present(raw, C):
            DEFECTS.append("settled describe returned a bare 404 without an error "
                           "message (assertion requires '404 with an error "
                           "message') — Type4_StateLogicViolation — "
                           f"raw={str(raw)[:150]}")

        # ---- churn-window adjudication ----
        for m in malformed:
            DEFECTS.append(f"churn window: 200 describe answer violates the "
                           f"full-config shape ({m}) — Type4_StateLogicViolation "
                           f"(qdrant_behavioral_collections_get_001)")
        for b4 in bad_404:
            DEFECTS.append(f"churn window: bare 404 without an error message "
                           f"({b4}) — Type4_StateLogicViolation "
                           f"(qdrant_behavioral_collections_get_001)")
        for o in odd_4xx:
            DEFECTS.append(f"churn window: describe answered {o} where only "
                           f"200-config / 404-with-message are legal mid-churn — "
                           f"Type4_StateLogicViolation")
        # 5xx / transport: strategy-7 reproduction rule (>=2) + liveness
        if five_xx:
            if alive():
                if len(five_xx) >= 2:
                    DEFECTS.append(f"churn window: {len(five_xx)} x 5xx answers on "
                                   f"describe while the lifecycle churned "
                                   f"(graceful 200-config or 404 was expected) — "
                                   f"Type3_RuntimeFailure — samples: {five_xx[:3]}")
                else:
                    print(f"OBSERVATION (inconclusive, <2 occurrences): {five_xx}")
            else:
                return "SCRIPT_ERROR"
        if transports:
            if alive():
                if len(transports) >= 2:
                    DEFECTS.append(f"churn window: {len(transports)} x transport "
                                   f"failures on describe with service alive — "
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
