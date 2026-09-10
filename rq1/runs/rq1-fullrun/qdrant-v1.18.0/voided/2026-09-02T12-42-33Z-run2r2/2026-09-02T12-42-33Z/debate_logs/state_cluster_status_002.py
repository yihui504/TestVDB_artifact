#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_cluster_status_002
# strategy: concurrent
# endpoint: cluster+status
# constraint_ids: qdrant_behavioral_cluster_status_001, qdrant_type_cluster_status_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/cluster-status
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (Concurrency State Blindness — cluster-view reads racing
#   committed point writes; the absolute-shape side of the type constraint is
#   owned by state_cluster_status_001 to avoid triple-counting one static finding)
"""
Attack: Strategy 4 (concurrent operations) on the global cluster face
  GET /cluster. Reader threads hammer the cluster-status face for a bounded
  window while writer threads perform verifiable committed writes (upsert
  unique points, wait=true) into one collection. Mutation-point justification
  (G6): every committed write advances internal consensus/cluster counters —
  a racy or cached serialization of the cluster view is most likely to leak a
  torn or state-inconsistent view exactly under write pressure, which is the
  one condition a plain sequential read never creates. A documented no-body
  control probe (R7 lesson) fixes the baseline fingerprint (result key set +
  cluster-mode value) before the race and is re-read after it. Judged
  signals: reader 5xx = Type3 after /healthz liveness (>=2 occurrences per
  the race reproduction rule; a single one is an inconclusive OBSERVATION);
  reader shape breaks (unparseable 200, result not an object, key set drift,
  cluster-mode value flip) = Type4 (>=2); writer 5xx on a valid wait=true
  body = concurrent corruption signal (>=2 = Type3 after liveness); final
  exact count must equal seed + accepted unique inserts (strategy-4
  count-consistency tail; drift = Type4); post-race control probe must be
  200 with the baseline fingerprint (single occurrence decisive —
  deterministic tail).
  [chunk_cluster+status coverage: concurrent(readers x committed writers,
   strategy 4) x qdrant_behavioral_cluster_status_001 (+ shape-stability
   clause of qdrant_type_cluster_status_001 under concurrency)]
Oracle: during the race every cluster-status read is 200 with a parseable
  result object whose key set and "status" value equal the baseline
  fingerprint (>=2 deviations = Type4_StateLogicViolation); no reader/writer
  5xx while /healthz stays 200 (>=2 = Type3_RuntimeFailure); after the race
  exact count == seed 4 + accepted unique inserts and the control probe
  returns 200 with the baseline fingerprint (mismatch = Type4)
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
    RACE_SECONDS = float(os.environ.get("TESTVDB_CLUSTER_STATUS_RACE_S", "4"))
except (TypeError, ValueError):
    RACE_SECONDS = 4.0


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


def exact_count(name):
    """Control read: exact point count or None on transport/parse failure."""
    s, raw = safe_request("POST", "count", body={"exact": True},
                          path_params={"name": name})
    if s != 200:
        return None
    node, err = parse_view(raw)
    if node is None or not isinstance(node.get("count"), int):
        return None
    return node["count"]


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scst2_" + TS + "_"
    C = PFX + "col"
    try:
        tot = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "20"))
    except (TypeError, ValueError):
        tot = 20
    n_readers = max(2, tot // 2)
    n_writers = max(2, tot - n_readers)
    print(f"[plan] readers={n_readers} writers={n_writers} window={RACE_SECONDS}s")
    DEFECTS = []
    lock = threading.Lock()
    bucket = {"r5xx": [], "rshape": [], "rtransport": [], "rother": [],
              "w5xx": [], "wother": [], "wtransport": []}
    accepted = {"points": 0}  # writer-accepted unique inserts (wait=true acked)
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

    def reader_thread(tid):
        i = 0
        deadline = time.time() + RACE_SECONDS
        while time.time() < deadline and i < 600:
            kind, detail = reader_probe(i)
            if kind == "ok":
                pass
            elif kind == "other":
                with lock:
                    bucket["rother"].append(f"r{tid}#{i}: {detail}")
            else:
                with lock:
                    key = "r5xx" if kind == "5xx" else (
                        "rshape" if kind == "shape" else "rtransport")
                    bucket[key].append(f"r{tid}#{i}: {detail}")
            i += 1
            time.sleep(0.01)
        with lock:
            print(f"[reader {tid}] finished after {i} probes")

    def writer_thread(tid):
        i = 0
        deadline = time.time() + RACE_SECONDS
        while time.time() < deadline and i < 400:
            # qdrant PointId = uint64 | UUID string only: use unique integer ids
            base_id = (tid + 1) * 10000000 + i * 10
            pts = [{"id": base_id + k, "vector": [0.1, 0.2, 0.3, 0.4]}
                   for k in range(2)]
            try:
                s, raw = safe_request("PUT", "upsert_points",
                                      body={"points": pts},
                                      path_params={"name": C},
                                      query_params={"wait": "true"})
            except Exception as e:
                with lock:
                    bucket["wtransport"].append(f"w{tid}#{i}: {str(e)[:120]}")
                i += 1
                continue
            if s in (200, 201):
                with lock:
                    accepted["points"] += len(pts)
            elif 500 <= s <= 599:
                with lock:
                    bucket["w5xx"].append(f"w{tid}#{i}: {s} raw={str(raw)[:150]}")
            elif s == 0:
                with lock:
                    bucket["wtransport"].append(f"w{tid}#{i}: {str(raw)[:120]}")
            else:
                with lock:
                    bucket["wother"].append(f"w{tid}#{i}: {s} raw={str(raw)[:120]}")
            i += 1
        with lock:
            print(f"[writer {tid}] finished after {i} batches")

    try:
        # ---- setup: collection + seed 4 points (wait=true) ----
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR create {C}: {err}")
            return "SCRIPT_ERROR"
        seed = [{"id": 900000 + k, "vector": [0.5, 0.5, 0.5, 0.5]}
                for k in range(4)]
        s, raw = safe_request("PUT", "upsert_points", body={"points": seed},
                              path_params={"name": C},
                              query_params={"wait": "true"})
        print(f"[seed upsert wait=true] status={s} raw={raw[:200]}")
        if s not in (200, 201):
            print(f"SETUP_ERROR: seed upsert = {s}")
            return "SCRIPT_ERROR"
        cnt0 = exact_count(C)
        print(f"[baseline count control] exact={cnt0} expected=4")
        if cnt0 is not None and cnt0 != 4:
            DEFECTS.append(
                f"baseline count control drift: expected 4, got {cnt0} — "
                f"Type4_StateLogicViolation"
            )

        # ---- documented no-body control probe (baseline fingerprint) ----
        s, raw = safe_request("GET", "cluster_status")
        print(f"[control probe: documented no-body GET] status={s} raw={raw[:300]}")
        if s == 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[control transport] /healthz probe status={hs} "
                  f"raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            print("ENV_ISSUE: transport failure on control probe — aborted")
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

        # ---- race window: readers x writers ----
        threads = [threading.Thread(target=reader_thread, args=(t,),
                                    daemon=True) for t in range(n_readers)]
        threads += [threading.Thread(target=writer_thread, args=(t,),
                                     daemon=True) for t in range(n_writers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=int(RACE_SECONDS * 4) + 60)

        time.sleep(1.0)  # settle async work before the deterministic tail

        # ---- final count control: seed + accepted unique inserts ----
        expected = 4 + accepted["points"]
        cnt = exact_count(C)
        print(f"[final count control] exact={cnt} expected={expected} "
              f"(seed 4 + accepted {accepted['points']})")
        if cnt is not None and cnt != expected:
            DEFECTS.append(
                f"final exact count after concurrent wait=true writes: "
                f"expected {expected}, got {cnt} — concurrent write loss/dup — "
                f"Type4_StateLogicViolation"
            )

        # ---- post-race control probe: baseline fingerprint must be back ----
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
                    f"post-race cluster-status probe returned {s} (200 "
                    f"promised, service alive per /healthz) — "
                    f"Type3_RuntimeFailure — raw={raw[:200]}"
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
                        f"Type4_StateLogicViolation"
                    )
                if node.get("status") != base["mode"]:
                    DEFECTS.append(
                        f"post-race cluster-mode value {node.get('status')!r} "
                        f"differs from baseline {base['mode']!r} — "
                        f"Type4_StateLogicViolation"
                    )

        # ---- race-window signals (reproduction rule: >=2 occurrences) ----
        if len(bucket["rshape"]) >= 2:
            DEFECTS.append(
                f"race window: {len(bucket['rshape'])} x shape deviation on "
                f"cluster-status reads while committed writes interleaved — "
                f"Type4_StateLogicViolation — samples: {bucket['rshape'][:3]}"
            )
        elif bucket["rshape"]:
            print(f"OBSERVATION (inconclusive, <2 occurrences): reader shape: "
                  f"{bucket['rshape']}")
        if len(bucket["r5xx"]) >= 2:
            if alive():
                DEFECTS.append(
                    f"race window: {len(bucket['r5xx'])} x 5xx on "
                    f"cluster-status reads (graceful 200 expected) — "
                    f"Type3_RuntimeFailure — samples: {bucket['r5xx'][:3]}"
                )
            else:
                return "SCRIPT_ERROR"
        elif bucket["r5xx"]:
            if not alive():
                return "SCRIPT_ERROR"
            print(f"OBSERVATION (inconclusive, <2 occurrences): reader 5xx: "
                  f"{bucket['r5xx']}")
        if len(bucket["w5xx"]) >= 2:
            if alive():
                DEFECTS.append(
                    f"race window: {len(bucket['w5xx'])} x 5xx on valid "
                    f"wait=true upserts under concurrency — "
                    f"Type3_RuntimeFailure — samples: {bucket['w5xx'][:3]}"
                )
            else:
                return "SCRIPT_ERROR"
        elif bucket["w5xx"]:
            if not alive():
                return "SCRIPT_ERROR"
            print(f"OBSERVATION (inconclusive, <2 occurrences): writer 5xx: "
                  f"{bucket['w5xx']}")
        if bucket["rother"]:
            print(f"OBSERVATION: non-200 4xx reader dispositions during race "
                  f"(recorded, not judged): {bucket['rother'][:3]}")
        if bucket["wother"]:
            print(f"OBSERVATION: unexpected writer dispositions during race "
                  f"(recorded, not judged): {bucket['wother'][:3]}")
        if (bucket["rtransport"] or bucket["wtransport"]) and not DEFECTS:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[transport tail] /healthz probe status={hs} "
                  f"raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            print(f"ENV_ISSUES: transport hiccups during race "
                  f"(liveness confirmed): "
                  f"{(bucket['rtransport'] + bucket['wtransport'])[:3]}")

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
    except Exception as _e:  # never exit without the strict VERDICT line
        print(f"FATAL: {_e}")
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
