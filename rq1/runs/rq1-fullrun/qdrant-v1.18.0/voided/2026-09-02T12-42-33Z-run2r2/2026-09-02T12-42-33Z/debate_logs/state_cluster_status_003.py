#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_cluster_status_003
# strategy: concurrent
# endpoint: cluster+status
# constraint_ids: qdrant_behavioral_cluster_status_001, qdrant_type_cluster_status_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/cluster-status
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (Concurrency State Blindness — collection lifecycle churn
#   racing the global cluster-view reader; the absolute-shape side of the type
#   constraint is owned by state_cluster_status_001)
"""
Attack: Strategy 7 (lifecycle x access concurrency) on the GLOBAL cluster
  face GET /cluster. Unlike the per-collection cluster-info face (which has
  a legal 404-while-absent disposition), the global cluster-status face has
  NO legal non-200 disposition: the behavioral assertion promises 200 with
  cluster info on a single-node deployment regardless of any collection's
  existence. Thread L cycles create->drop of one collection (the cluster's
  collection registry churns); thread R continuously reads the global face.
  Mutation-point justification (G6): the cluster view summarizes the
  collection registry — mid-registry-mutation reads are exactly where torn,
  stale or absent views classically leak (the timing window between a drop
  and the next create flips the registry state the view summarizes, the most
  destructive mutation for a summarizing read). A documented no-body control
  probe (R7 lesson) fixes the baseline fingerprint before the race and is
  re-read after it. Judged signals: reader 5xx during the race = Type3 after
  /healthz liveness (>=2 occurrences per the race reproduction rule); reader
  shape breaks (unparseable 200, result not an object, key-set drift,
  cluster-mode flip) = Type4 (>=2); ANY non-200 4xx on this global face is
  recorded as OBSERVATION (no per-collection dependency is documented, but
  4xx here is not contract-adjudicable); post-race after verifiable drop
  (describe control = 404) the control probe must return exactly 200 with
  the baseline fingerprint (single occurrence decisive — deterministic tail).
  [chunk_cluster+status coverage: concurrent(lifecycle churn, strategy 7) x
   qdrant_behavioral_cluster_status_001 (+ shape-stability clause of
   qdrant_type_cluster_status_001 under lifecycle churn)]
Oracle: during the churn every global cluster-status read is 200 with a
  parseable result object whose key set and "status" value equal the
  baseline fingerprint (>=2 deviations = Type4_StateLogicViolation; >=2 5xx
  = Type3_RuntimeFailure after /healthz 200); after the final verified drop
  the control probe returns exactly 200 with the baseline fingerprint
  (non-200 = Type3 after liveness; fingerprint mismatch = Type4)
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

try:
    N_CYCLES = max(3, int(os.environ.get("TESTVDB_CLUSTER_STATUS_CYCLES", "10")))
except (TypeError, ValueError):
    N_CYCLES = 10


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """Forwarding wrapper (R7 standing lesson: timeout/path_params/body/
    query_params forwarded exactly; all HTTP exits go through here)."""
    return rt.request(method, path_key, body=body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def alive():
    """Liveness re-check via the lightweight documented health endpoint."""
    hs, hraw = rt.request("GET", "healthz")
    print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def parse_view(raw):
    """Return (result_dict, None) on a parseable 200 body else (None, detail)."""
    try:
        b = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        return None, f"unparseable body ({e})"
    if not isinstance(b, dict):
        return None, "top-level body not an object"
    node = b.get("result")
    if not isinstance(node, dict):
        return None, "result envelope not an object"
    return node, None


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scst3_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []
    lock = threading.Lock()
    stop_evt = threading.Event()
    bucket = {"r5xx": [], "rshape": [], "rtransport": [], "rother": []}
    base = {"keys": None, "mode": None}

    def reader_probe(idx):
        """One reader pass -> ('ok'|'5xx'|'shape'|'transport'|'other', detail)."""
        try:
            s, raw = safe_request("GET", "cluster_status", timeout=8)
        except Exception as e:
            return "transport", str(e)[:120]
        if s == 0:
            return "transport", str(raw)[:120]
        if 500 <= s <= 599:
            return "5xx", f"{s} raw={str(raw)[:150]}"
        if s != 200:
            return "other", f"{s} raw={str(raw)[:120]}"
        node, err = parse_view(raw)
        if node is None:
            return "shape", f"200 but {err}"
        if base["keys"] is not None and frozenset(node.keys()) != base["keys"]:
            return "shape", (f"key set drift {sorted(base['keys'])} -> "
                             f"{sorted(node.keys())}")
        if base["mode"] is not None and node.get("status") != base["mode"]:
            return "shape", (f"cluster-mode flip {base['mode']!r} -> "
                             f"{node.get('status')!r}")
        return "ok", ""

    def lifecycle_thread():
        for i in range(N_CYCLES):
            if stop_evt.is_set():
                return
            try:
                ok, err = rt.setup_default(C, 4, "Cosine")
                if not ok:
                    print(f"[L#{i}] create not ok: {err[:120]}")
            except Exception as e:
                print(f"[L#{i}] create exception: {e}")
            time.sleep(0.08)
            try:
                safe_request("DELETE", "drop_collection",
                             path_params={"name": C})
            except Exception as e:
                print(f"[L#{i}] drop exception: {e}")
            time.sleep(0.08)
        with lock:
            print("[L] lifecycle loop finished")

    def reader_thread():
        for i in range(N_CYCLES * 12):
            if stop_evt.is_set():
                return
            kind, detail = reader_probe(i)
            if kind == "ok":
                pass
            elif kind == "other":
                with lock:
                    bucket["rother"].append(f"R#{i}: {detail}")
            else:
                with lock:
                    key = "r5xx" if kind == "5xx" else (
                        "rshape" if kind == "shape" else "rtransport")
                    bucket[key].append(f"R#{i}: {detail}")
            time.sleep(0.02)
        with lock:
            print("[R] reader loop finished")

    try:
        # ---- documented no-body control probe (baseline fingerprint) ----
        s, raw = safe_request("GET", "cluster_status")
        print(f"[control probe: documented no-body GET] status={s} raw={raw[:300]}")
        if s == 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[control transport] /healthz probe status={hs} "
                  f"raw={str(hraw)[:120]}")
            return "SCRIPT_ERROR"
        if s != 200:
            print(f"SETUP_ERROR: control probe = {s}")
            return "SCRIPT_ERROR"
        node, err = parse_view(raw)
        if node is None:
            print(f"SETUP_ERROR: control probe result not an object: {err}")
            return "SCRIPT_ERROR"
        base["keys"] = frozenset(node.keys())
        base["mode"] = node.get("status")
        print(f"[fingerprint] keys={sorted(base['keys'])} mode={base['mode']!r}")

        # seed: C exists once so the churn races a live collection from step 1
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR create {C}: {err}")
            return "SCRIPT_ERROR"

        # ---- race window: lifecycle churn x global-face reads ----
        threads = [
            threading.Thread(target=lifecycle_thread, daemon=True),
            threading.Thread(target=reader_thread, daemon=True),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=180)
        stop_evt.set()

        # ---- quiescence: C must be verifiably gone before the final tail ----
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
        print(f"[quiescence] describe({C}) -> 404? {gone}")
        if not gone:
            try:
                rt.drop_collection(C)
            except Exception:
                pass
            time.sleep(1.0)
        time.sleep(0.8)  # settle async cleanup

        # ---- post-race control probe: exactly 200 with baseline fingerprint ----
        s, raw = safe_request("GET", "cluster_status")
        print(f"[post-race control probe] status={s} raw={raw[:300]}")
        if s == 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[post-race transport] /healthz probe status={hs} "
                  f"raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            print("ENV_ISSUE: transport failure on post-race probe — skipped")
        elif 500 <= s <= 599:
            if alive():
                DEFECTS.append(
                    f"post-race global cluster-status probe returned {s} "
                    f"(200 promised with no per-collection dependency, service "
                    f"alive per /healthz) — Type3_RuntimeFailure — "
                    f"raw={raw[:200]}"
                )
            else:
                return "SCRIPT_ERROR"
        elif s == 200:
            node, err = parse_view(raw)
            if node is None:
                DEFECTS.append(
                    f"post-race 200 but {err} — promised ClusterStatus object "
                    f"— Type4_StateLogicViolation — raw={raw[:200]}"
                )
            else:
                if frozenset(node.keys()) != base["keys"]:
                    DEFECTS.append(
                        f"post-race cluster-view key set differs from baseline "
                        f"({sorted(base['keys'])} -> {sorted(node.keys())}) — "
                        f"lifecycle churn corrupted the global view — "
                        f"Type4_StateLogicViolation"
                    )
                if node.get("status") != base["mode"]:
                    DEFECTS.append(
                        f"post-race cluster-mode value {node.get('status')!r} "
                        f"differs from baseline {base['mode']!r} — "
                        f"Type4_StateLogicViolation"
                    )
        else:
            print(f"OBSERVATION: post-race probe returned {s} — unexpected "
                  f"disposition on the global face, recorded, not judged")

        # ---- race-window signals (reproduction rule: >=2 occurrences) ----
        if len(bucket["rshape"]) >= 2:
            DEFECTS.append(
                f"race window: {len(bucket['rshape'])} x shape deviation on "
                f"global cluster-status reads while the collection lifecycle "
                f"churned — Type4_StateLogicViolation — samples: "
                f"{bucket['rshape'][:3]}"
            )
        elif bucket["rshape"]:
            print(f"OBSERVATION (inconclusive, <2 occurrences): reader shape: "
                  f"{bucket['rshape']}")
        if len(bucket["r5xx"]) >= 2:
            if alive():
                DEFECTS.append(
                    f"race window: {len(bucket['r5xx'])} x 5xx on global "
                    f"cluster-status reads while the collection lifecycle "
                    f"churned (200 always promised; no per-collection "
                    f"dependency) — Type3_RuntimeFailure — samples: "
                    f"{bucket['r5xx'][:3]}"
                )
            else:
                return "SCRIPT_ERROR"
        elif bucket["r5xx"]:
            if not alive():
                return "SCRIPT_ERROR"
            print(f"OBSERVATION (inconclusive, <2 occurrences): reader 5xx: "
                  f"{bucket['r5xx']}")
        if bucket["rother"]:
            print(f"OBSERVATION: non-200 dispositions on the global face "
                  f"during churn (no legal non-200 documented; recorded, not "
                  f"adjudicated): {bucket['rother'][:3]}")
        if bucket["rtransport"] and not DEFECTS:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[transport tail] /healthz probe status={hs} "
                  f"raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            print(f"ENV_ISSUES: transport hiccups during churn "
                  f"(liveness confirmed): {bucket['rtransport'][:3]}")

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
    except Exception as _e:  # never exit without the strict VERDICT line
        print(f"FATAL: {_e}")
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
