#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_cluster_recover_004
# strategy: count_consistency
# endpoint: cluster+recover
# constraint_ids: qdrant_state_cluster_recover_001, qdrant_behavioral_cluster_recover_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/recover-current-peer
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 Concurrency State Blindness
"""
Attack: Strategy 1 (count/state invariance) run under a Strategy 7-style
  lifecycle churn loop on POST /cluster/recover (URL from raw_knowledge
  api_endpoints[].url, registered into rt.PATHS). Blindspot BS-03 mapped to
  the read side: a lifecycle thread fires REPEATS=5 recover calls while reader
  threads continuously poll the three state faces — GET /cluster (cluster
  membership face), POST count exact=true (data-plane cardinality), GET
  /collections/{c} (collection registry face). No mutation touches the points
  during the window, so every read must observe the unchanged world: exact
  count == 8 on every 200 response, describe 200, cluster face 200. Judged
  signals (sporadic-race guard: an event must recur >=2 times to be a
  finding, single occurrences are recorded as OBSERVATION): count drift
  (Type4_StateLogicViolation — churn leaked into the data plane), describe 404
  (Type4 — collection state destroyed transiently), any-face 5xx
  (Type3_RuntimeFailure only after /healthz liveness). The quiesced final
  check after churn joins is strict with no tolerance: /healthz 200 within the
  grace window, describe 200, exact count == 8, GET /cluster 200. Standalone
  "Distributed mode disabled" 4xx dispositions on the recover calls are
  recorded as OBSERVATION per the R6 lesson — the read-face invariance legs
  stay falsifiable regardless of the recover disposition family.
  G6 mutation justification: the churn loop repeats the destructive op at
  sub-second spacing so a reader can catch the intermediate state a single
  call would hide (torn membership state, transient registry loss).
  [chunk_cluster+recover coverage: count_consistency x
   qdrant_state_cluster_recover_001 (data-plane and cluster-face invariance
   under operational churn) + qdrant_behavioral_cluster_recover_001
   (dispositions across repeated calls under concurrent reads)]
Oracle: during the churn window every 200 count response reports count == 8
  (>=2 drift readings = Type4_StateLogicViolation, 1 = observation), every
  describe response is 200 (>=2 404 readings = Type4_StateLogicViolation),
  every GET /cluster response is 200 (>=2 5xx readings across all faces =
  Type3_RuntimeFailure only after /healthz returns 200); after churn joins:
  /healthz 200 within the 20s grace window (never-200 = Type3),
  GET /collections/{c} -> 200 (404 = Type4), exact count == 8 (drift =
  Type4), GET /cluster -> 200 (5xx = Type3 only after liveness).
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
REPEATS = 5
N = 8
DIM = 4
THREADS_ENV = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "20"))
READERS = max(1, min(THREADS_ENV // 4, 3))


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
    PFX = "screc4_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []

    lock = threading.Lock()
    tally = {"count_drift": 0, "describe_404": 0, "any_5xx": 0,
             "reads_ok": 0, "cluster_non200": 0}
    thread_errors = []
    stop = threading.Event()

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

        # ---- setup: quiesced baseline ----
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR create {C}: {err}")
            return "SCRIPT_ERROR"
        pts = [{"id": i, "vector": [0.1 * (i + 1), 0.2, 0.3, 0.4],
                "payload": {"batch": "seed"}} for i in range(N)]
        s, raw = upsert_wait(C, pts)
        print(f"[seed upsert wait=true] status={s} raw={raw[:200]}")
        if s not in (200, 201):
            print(f"SETUP_ERROR seed upsert {s}: {raw[:200]}")
            return "SCRIPT_ERROR"
        sc, n0, craw_c = exact_count(C)
        print(f"[baseline exact count] status={sc} count={n0} raw={craw_c[:200]}")
        if sc != 200 or n0 != N:
            print(f"SETUP_ERROR baseline count status={sc} count={n0} (expected {N})")
            return "SCRIPT_ERROR"

        def churn():
            """Lifecycle thread: REPEATS recover calls at sub-second spacing."""
            try:
                for i in range(REPEATS):
                    s, raw = safe_request("POST", "cluster_recover")
                    print(f"[churn recover #{i + 1}] status={s} raw={raw[:200]}")
                    if 400 <= s <= 499 and "distributed" in str(raw).lower():
                        print(f"OBSERVATION (mask, churn #{i + 1}): standalone "
                              f"distributed-mode gate — recorded")
                    time.sleep(0.2)
            except Exception as e:
                with lock:
                    thread_errors.append(f"churn: {e!r}")
            finally:
                stop.set()

        def reader():
            """Reader thread: poll the three state faces until churn ends."""
            try:
                while not stop.is_set():
                    s, raw = safe_request("GET", "cluster_status")
                    with lock:
                        if s == 200:
                            tally["reads_ok"] += 1
                        elif 500 <= s <= 599:
                            tally["any_5xx"] += 1
                            print(f"[reader GET /cluster] 5xx status={s} raw={raw[:120]}")
                        elif s != 0:
                            tally["cluster_non200"] += 1
                    s, n, raw = exact_count(C)
                    with lock:
                        if s == 200 and n is not None and n != N:
                            tally["count_drift"] += 1
                            print(f"[reader count] drift count={n} expected={N}")
                        elif 500 <= s <= 599:
                            tally["any_5xx"] += 1
                            print(f"[reader count] 5xx status={s} raw={raw[:120]}")
                    s, raw = safe_request("GET", "describe_collection",
                                          path_params={"name": C})
                    with lock:
                        if s == 404:
                            tally["describe_404"] += 1
                            print(f"[reader describe] 404 during churn raw={raw[:120]}")
                        elif 500 <= s <= 599:
                            tally["any_5xx"] += 1
                            print(f"[reader describe] 5xx status={s} raw={raw[:120]}")
                    time.sleep(0.03)
            except Exception as e:
                with lock:
                    thread_errors.append(f"reader: {e!r}")

        threads = [threading.Thread(target=reader) for _ in range(READERS)]
        threads.append(threading.Thread(target=churn))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        print(f"[tally] readers={READERS} reads_ok={tally['reads_ok']} "
              f"count_drift={tally['count_drift']} describe_404={tally['describe_404']} "
              f"any_5xx={tally['any_5xx']} cluster_non200={tally['cluster_non200']} "
              f"thread_errors={thread_errors}")
        if thread_errors:
            print(f"ENV_ISSUE: worker thread exceptions (script-side): {thread_errors}")
            return "SCRIPT_ERROR"

        # ---- mid-churn signals (>=2 recurrence = finding; 1 = observation) ----
        if tally["count_drift"] >= 2:
            DEFECTS.append(
                f"exact count drifted off {N} in {tally['count_drift']} reads "
                f"during the recover churn loop with NO point mutations — "
                f"operational churn leaked into the data plane — "
                f"Type4_StateLogicViolation"
            )
        elif tally["count_drift"] == 1:
            print("OBSERVATION: single count-drift reading during churn — "
                  "inconclusive per the race false-positive guard, recorded")
        if tally["describe_404"] >= 2:
            DEFECTS.append(
                f"GET /collections/{C} returned 404 in "
                f"{tally['describe_404']} reads during the recover churn loop "
                f"— transient collection-registry loss — "
                f"Type4_StateLogicViolation"
            )
        elif tally["describe_404"] == 1:
            print("OBSERVATION: single describe-404 reading during churn — "
                  "inconclusive per the race false-positive guard, recorded")
        if tally["any_5xx"] >= 2:
            if not liveness_ok():
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"{tally['any_5xx']} 5xx responses across state faces during "
                f"the recover churn loop (service alive per /healthz) — "
                f"Type3_RuntimeFailure"
            )
        elif tally["any_5xx"] == 1:
            print("OBSERVATION: single 5xx reading during churn — "
                  "inconclusive per the race false-positive guard, recorded")

        # ---- quiesced final check: strict, no tolerance ----
        if not grace_liveness(GRACE_S):
            DEFECTS.append(
                f"after the recover churn loop /healthz never returned 200 "
                f"within {GRACE_S}s — Type3_RuntimeFailure"
            )
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"

        ds, draw = safe_request("GET", "describe_collection", path_params={"name": C})
        print(f"[final describe] status={ds} raw={draw[:200]}")
        if ds == 404:
            DEFECTS.append(
                f"GET /collections/{C} returned 404 after the churn loop "
                f"quiesced — collection state destroyed — "
                f"Type4_StateLogicViolation"
            )
        elif ds == 0 or 500 <= ds <= 599:
            if not liveness_ok():
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"describe after churn returned {ds} (200 expected; service "
                f"alive per /healthz) — Type3_RuntimeFailure — raw={draw[:200]}"
            )

        sc2, n1, craw2 = exact_count(C)
        print(f"[final exact count] status={sc2} count={n1} expected={N} "
              f"raw={craw2[:200]}")
        if sc2 == 200 and n1 is not None and n1 != N:
            DEFECTS.append(
                f"quiesced exact count after churn is {n1}, expected {N} — "
                f"Type4_StateLogicViolation"
            )
        elif sc2 == 0 or 500 <= sc2 <= 599:
            if not liveness_ok():
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"count after churn returned {sc2} (200 expected; service "
                f"alive per /healthz) — Type3_RuntimeFailure — raw={craw2[:200]}"
            )

        cs2, craw3 = safe_request("GET", "cluster_status")
        print(f"[final GET /cluster] status={cs2} raw={craw3[:200]}")
        if cs2 == 0 or 500 <= cs2 <= 599:
            if not liveness_ok():
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"GET /cluster after churn returned {cs2} (200 expected; "
                f"service alive per /healthz) — Type3_RuntimeFailure — "
                f"raw={craw3[:200]}"
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
