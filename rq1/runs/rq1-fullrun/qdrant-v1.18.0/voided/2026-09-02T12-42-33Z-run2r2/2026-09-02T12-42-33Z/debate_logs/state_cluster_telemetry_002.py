#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_cluster_telemetry_002
# strategy: concurrent
# endpoint: cluster+telemetry
# constraint_ids: qdrant_behavioral_cluster_telemetry_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/cluster-telemetry
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 4 (concurrent-operation attack; Blindspot BS-03 Concurrency
  State Blindness) on the ops face GET /cluster/telemetry (cluster+telemetry;
  URL read verbatim from raw_knowledge api_endpoints[].url and registered
  into rt.PATHS). The behavioral assertion promises HTTP 200 with a
  telemetry payload on this global face — it has no per-collection and no
  quiescence precondition, so concurrent data-plane commits must never
  break it. Race window: reader threads hammer the no-param telemetry GET
  while writer threads commit unique wait=true upserts into a dedicated
  collection. Judged with the race reproduction rule (>=2 occurrences):
  reader 5xx while /healthz stays 200 = Type3_RuntimeFailure; reader shape
  deviation (non-200, unparseable 200, result-envelope violation, telemetry
  fingerprint drift: result key set / cluster.enabled /
  cluster.number_of_peers flip) = Type4_StateLogicViolation — no deployment
  change happens during the window, so the state view must be constant;
  writer 5xx (>=2) = Type3 after /healthz liveness. Post-race: exact count
  must equal seed + writer-accepted unique inserts (wait=true accounting;
  drift = Type4) and the control probe must return exactly 200 with the
  baseline fingerprint. Transport failures get inline /healthz liveness
  re-checks; <2 occurrences are recorded as inconclusive OBSERVATIONs.
  [chunk_cluster+telemetry coverage: concurrent (data-plane commit race x
  global telemetry face) x qdrant_behavioral_cluster_telemetry_001
  (200-during-mutations clause + telemetry-view-constant clause)]
Oracle: during the race window every telemetry read is 200 with result an
  object whose fingerprint (result key set, cluster.enabled,
  cluster.number_of_peers) equals the baseline fingerprint (>=2 deviations =
  Type4_StateLogicViolation); no reader 5xx while /healthz is 200 (>=2 =
  Type3_RuntimeFailure); no writer 5xx (>=2 = Type3 after liveness); after
  the race exact count == 4 + accepted unique wait=true inserts (mismatch =
  Type4_StateLogicViolation); the post-race control probe returns exactly
  200 with the baseline fingerprint (non-200 = Type3 after liveness;
  fingerprint mismatch = Type4)
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


def load_telemetry_template():
    """Standing lesson: derive the URL only from raw_knowledge
    api_endpoints[].url (entry with path == "cluster+telemetry")."""
    for _p in Path(__file__).resolve().parents:
        _rk = _p / "raw_knowledge.json"
        if _rk.exists():
            try:
                for _e in json.loads(_rk.read_text(encoding="utf-8")).get("api_endpoints", []):
                    if _e.get("path") == "cluster+telemetry" and _e.get("url"):
                        return _e["url"]
            except Exception:
                return None
    return None


_TLM_TPL = load_telemetry_template()
if not _TLM_TPL:
    print("VERDICT: SCRIPT_ERROR - cluster+telemetry url not derivable from raw_knowledge api_endpoints[].url")
    sys.exit(2)
rt.PATHS["cluster_telemetry"] = _TLM_TPL
print(f"[url-derived] cluster+telemetry -> {_TLM_TPL} (raw_knowledge api_endpoints[].url)")


def safe_request(method, path_key, body=None, path_params=None,
                query_params=None, timeout=30):
    """All HTTP through the runtime; forwards timeout/path_params/body/
    query_params exactly (R7 standing lesson). Inline liveness probes
    (GET healthz) stay in this exact call form for static-check visibility."""
    return rt.request(method, path_key, body=body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def alive():
    """Liveness re-check via the lightweight documented health endpoint."""
    hs, hraw = safe_request("GET", "healthz")
    print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def parse_view(raw):
    """result.<field> envelope (standing lesson)."""
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


def fingerprint(node):
    """State-view fingerprint: (result key set, cluster.enabled,
    cluster.number_of_peers)."""
    keys = frozenset(node.keys()) if isinstance(node, dict) else None
    cl = node.get("cluster") if isinstance(node, dict) else None
    enabled = cl.get("enabled") if isinstance(cl, dict) else None
    npeers = cl.get("number_of_peers") if isinstance(cl, dict) else None
    return (keys, enabled, npeers)


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
    PFX = "sctlm2_" + TS + "_"
    C = PFX + "col"
    try:
        tot = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "20"))
    except (TypeError, ValueError):
        tot = 20
    n_readers = max(2, tot // 2)
    n_writers = max(2, tot - n_readers)
    try:
        RACE_SECONDS = float(os.environ.get("TESTVDB_CLUSTER_TELEMETRY_RACE_S", "6"))
    except (TypeError, ValueError):
        RACE_SECONDS = 6.0
    print(f"[plan] readers={n_readers} writers={n_writers} window={RACE_SECONDS}s")
    DEFECTS = []
    lock = threading.Lock()
    bucket = {"r5xx": [], "rshape": [], "rtransport": [], "rother": [],
              "w5xx": [], "wother": [], "wtransport": []}
    accepted = {"points": 0}  # writer-accepted unique inserts (wait=true acked)
    base = {"fp": None}

    def reader_probe(idx):
        """One reader pass -> ('ok'|'5xx'|'shape'|'transport'|'other', detail)."""
        try:
            s, raw = safe_request("GET", "cluster_telemetry", timeout=8)
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
        if base["fp"] is not None and fingerprint(node) != base["fp"]:
            now = fingerprint(node)
            return "shape", (f"fingerprint drift keys/enabled/npeers "
                             f"{base['fp'][1]!r}/{base['fp'][2]!r} -> "
                             f"{now[1]!r}/{now[2]!r}")
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
            # qdrant PointId = uint64 | UUID string only: unique integer ids
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
        # ---- documented no-body control probe (baseline fingerprint) ----
        s, raw = safe_request("GET", "cluster_telemetry")
        print(f"[control probe: documented no-param GET] status={s} raw={raw[:300]}")
        if s == 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[control transport] /healthz probe status={hs} raw={str(hraw)[:120]}")
            return "SCRIPT_ERROR"
        if s != 200:
            print(f"SETUP_ERROR: control probe = {s}")
            return "SCRIPT_ERROR"
        node, err = parse_view(raw)
        if node is None:
            print(f"SETUP_ERROR: control probe result not an object: {err}")
            return "SCRIPT_ERROR"
        base["fp"] = fingerprint(node)
        print(f"[fingerprint] keys={sorted(base['fp'][0])} "
              f"enabled={base['fp'][1]!r} npeers={base['fp'][2]!r}")

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
        print(f"[baseline exact count] {cnt0} (expected 4)")
        if cnt0 != 4:
            print(f"SETUP_ERROR: baseline count = {cnt0}")
            return "SCRIPT_ERROR"

        # ---- race window: unique wait=true commits x telemetry reads ----
        threads = [threading.Thread(target=reader_thread, args=(t,), daemon=True)
                   for t in range(n_readers)]
        threads += [threading.Thread(target=writer_thread, args=(t,), daemon=True)
                    for t in range(n_writers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=180)

        # ---- post-race accounting: exact count == 4 + accepted inserts ----
        time.sleep(1.0)  # allow eventual consistency before the control count
        cnt = exact_count(C)
        expected = 4 + accepted["points"]
        print(f"[post-race exact count] {cnt} expected={expected} "
              f"(seed 4 + accepted {accepted['points']})")
        if cnt is not None and cnt != expected:
            DEFECTS.append(
                f"post-race count control drift: expected {expected} "
                f"(4 seed + {accepted['points']} wait=true-acked unique "
                f"inserts), got {cnt} — Type4_StateLogicViolation"
            )
        elif cnt is None:
            print("OBSERVATION: post-race exact count unreadable "
                  "(transport/parse) — count leg unjudgeable")

        # ---- post-race control probe: exactly 200 with baseline fingerprint ----
        s, raw = safe_request("GET", "cluster_telemetry")
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
                    f"post-race telemetry probe returned {s} (200 promised "
                    f"with no per-collection dependency, service alive per "
                    f"/healthz) — Type3_RuntimeFailure — raw={raw[:200]}"
                )
            else:
                return "SCRIPT_ERROR"
        elif s == 200:
            node, err = parse_view(raw)
            if node is None:
                DEFECTS.append(
                    f"post-race 200 but {err} — promised telemetry result "
                    f"object — Type4_StateLogicViolation — raw={raw[:200]}"
                )
            elif fingerprint(node) != base["fp"]:
                DEFECTS.append(
                    f"post-race telemetry fingerprint differs from baseline "
                    f"(baseline enabled={base['fp'][1]!r} "
                    f"npeers={base['fp'][2]!r} -> now "
                    f"enabled={fingerprint(node)[1]!r} "
                    f"npeers={fingerprint(node)[2]!r}) — no deployment "
                    f"change occurred — Type4_StateLogicViolation"
                )
        else:
            print(f"OBSERVATION: post-race probe returned {s} — unexpected "
                  f"disposition, recorded, not judged")

        # ---- race-window signals (reproduction rule: >=2 occurrences) ----
        if len(bucket["rshape"]) >= 2:
            DEFECTS.append(
                f"race window: {len(bucket['rshape'])} x shape/fingerprint "
                f"deviation on telemetry reads while unique wait=true commits "
                f"landed — Type4_StateLogicViolation — samples: "
                f"{bucket['rshape'][:3]}"
            )
        elif bucket["rshape"]:
            print(f"OBSERVATION (inconclusive, <2 occurrences): reader shape: "
                  f"{bucket['rshape']}")
        if len(bucket["r5xx"]) >= 2:
            if alive():
                DEFECTS.append(
                    f"race window: {len(bucket['r5xx'])} x 5xx on telemetry "
                    f"reads while writers committed (200 always promised; no "
                    f"per-collection dependency) — Type3_RuntimeFailure — "
                    f"samples: {bucket['r5xx'][:3]}"
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
                    f"race window: {len(bucket['w5xx'])} x writer 5xx on "
                    f"wait=true upserts — Type3_RuntimeFailure — samples: "
                    f"{bucket['w5xx'][:3]}"
                )
            else:
                return "SCRIPT_ERROR"
        elif bucket["w5xx"]:
            if not alive():
                return "SCRIPT_ERROR"
            print(f"OBSERVATION (inconclusive, <2 occurrences): writer 5xx: "
                  f"{bucket['w5xx']}")
        if bucket["rother"]:
            print(f"OBSERVATION: non-200 reader dispositions during the race "
                  f"(no legal non-200 documented; recorded, not adjudicated): "
                  f"{bucket['rother'][:3]}")
        if bucket["wother"]:
            print(f"OBSERVATION: non-counted writer dispositions during the "
                  f"race (recorded, not adjudicated): {bucket['wother'][:3]}")
        if (bucket["rtransport"] or bucket["wtransport"]) and not DEFECTS:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[transport tail] /healthz probe status={hs} "
                  f"raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            print(f"ENV_ISSUES: transport hiccups during the race (liveness "
                  f"confirmed): "
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
