#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_cluster_telemetry_003
# strategy: concurrent
# endpoint: cluster+telemetry
# constraint_ids: qdrant_behavioral_cluster_telemetry_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/cluster-telemetry
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 7 (lifecycle concurrency attack; Blindspot BS-03
  Concurrency State Blindness) on the ops face GET /cluster/telemetry
  (cluster+telemetry; URL read verbatim from raw_knowledge
  api_endpoints[].url and registered into rt.PATHS). While thread L cycles
  create->drop of one collection (the deployment's lifecycle churn), reader
  threads hammer the global telemetry face. The behavioral assertion
  promises HTTP 200 with a telemetry payload on this face — a temporarily
  absent collection is not a legal reason for a 500/internal error (the
  global ops face has no per-collection dependency), and no deployment
  change happens, so the telemetry state-view fingerprint (result key set,
  cluster.enabled, cluster.number_of_peers) must stay constant. Judged with
  the race reproduction rule (>=2 occurrences): reader 5xx while /healthz
  stays 200 = Type3_RuntimeFailure (mirrors the qdrant #9229 family:
  internal error during lifecycle races); reader shape deviation (non-200,
  unparseable 200, result-envelope violation, fingerprint drift) = Type4.
  Post-churn tail: after the final verified drop (describe = 404) the
  control probe must return exactly 200 with the baseline fingerprint, and
  the collection must leave no residual in the collections list
  (list_collections still reporting it = stale/residual state = Type4).
  4xx dispositions on the global face are recorded as OBSERVATION (no legal
  non-200 documented, but single-face 4xx carries no race proof).
  [chunk_cluster+telemetry coverage: concurrent (collection lifecycle churn
  x global telemetry face + post-churn residual check) x
  qdrant_behavioral_cluster_telemetry_001 (200-during-lifecycle clause +
  no-residual-state clause)]
Oracle: during collection create/drop churn every global GET
  /cluster/telemetry read is 200 with result an object whose fingerprint
  (result key set, cluster.enabled, cluster.number_of_peers) equals the
  baseline fingerprint (>=2 deviations = Type4_StateLogicViolation; >=2 5xx
  = Type3_RuntimeFailure after /healthz 200); after the final verified drop
  (describe = 404) the control probe returns exactly 200 with the baseline
  fingerprint (non-200 = Type3 after liveness; fingerprint mismatch =
  Type4) and GET /collections no longer lists the churned collection
  (residual = Type4_StateLogicViolation)
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

try:
    N_CYCLES = max(3, int(os.environ.get("TESTVDB_CLUSTER_TELEMETRY_CYCLES", "12")))
except (TypeError, ValueError):
    N_CYCLES = 12


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


def listed_collections():
    """GET /collections -> set of collection names or None on failure.
    (collections+list returns result as a LIST of {name} entries — parsed
    directly here; parse_view is dict-only and would misread this face.)"""
    s, raw = safe_request("GET", "list_collections")
    if s != 200:
        return None
    try:
        b = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    if not isinstance(b, dict) or not isinstance(b.get("result"), list):
        return None
    names = set()
    for entry in b["result"]:
        if isinstance(entry, dict) and isinstance(entry.get("name"), str):
            names.add(entry["name"])
    return names


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sctlm3_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []
    lock = threading.Lock()
    stop_evt = threading.Event()
    bucket = {"r5xx": [], "rshape": [], "rtransport": [], "rother": []}
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
        s, raw = safe_request("GET", "cluster_telemetry")
        print(f"[control probe: documented no-param GET] status={s} raw={raw[:300]}")
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
        base["fp"] = fingerprint(node)
        print(f"[fingerprint] keys={sorted(base['fp'][0])} "
              f"enabled={base['fp'][1]!r} npeers={base['fp'][2]!r}")

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

        # ---- post-churn control probe: exactly 200 with baseline fingerprint ----
        s, raw = safe_request("GET", "cluster_telemetry")
        print(f"[post-churn control probe] status={s} raw={raw[:300]}")
        if s == 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[post-churn transport] /healthz probe status={hs} "
                  f"raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            print("ENV_ISSUE: transport failure on post-churn probe — skipped")
        elif 500 <= s <= 599:
            if alive():
                DEFECTS.append(
                    f"post-churn telemetry probe returned {s} (200 promised "
                    f"with no per-collection dependency, service alive per "
                    f"/healthz) — Type3_RuntimeFailure — raw={raw[:200]}"
                )
            else:
                return "SCRIPT_ERROR"
        elif s == 200:
            node, err = parse_view(raw)
            if node is None:
                DEFECTS.append(
                    f"post-churn 200 but {err} — promised telemetry result "
                    f"object — Type4_StateLogicViolation — raw={raw[:200]}"
                )
            else:
                if fingerprint(node) != base["fp"]:
                    DEFECTS.append(
                        f"post-churn telemetry fingerprint differs from "
                        f"baseline (baseline enabled={base['fp'][1]!r} "
                        f"npeers={base['fp'][2]!r} -> now "
                        f"enabled={fingerprint(node)[1]!r} "
                        f"npeers={fingerprint(node)[2]!r}) — lifecycle "
                        f"churn corrupted the telemetry state view — "
                        f"Type4_StateLogicViolation"
                    )
        else:
            print(f"OBSERVATION: post-churn probe returned {s} — unexpected "
                  f"disposition on the global face, recorded, not judged")

        # ---- residual check: the churned collection must leave no trace ----
        names = listed_collections()
        print(f"[residual check] {C} in collections list? "
              f"{names is not None and C in (names or set())}")
        if names is not None and C in names:
            DEFECTS.append(
                f"residual state: churned collection {C} still listed by "
                f"GET /collections after a verified drop (describe = 404) — "
                f"Type4_StateLogicViolation"
            )
        elif names is None:
            print("OBSERVATION: collections list unreadable — residual leg "
                  "unjudgeable")

        # ---- race-window signals (reproduction rule: >=2 occurrences) ----
        if len(bucket["rshape"]) >= 2:
            DEFECTS.append(
                f"race window: {len(bucket['rshape'])} x shape/fingerprint "
                f"deviation on telemetry reads while the collection "
                f"lifecycle churned — Type4_StateLogicViolation — samples: "
                f"{bucket['rshape'][:3]}"
            )
        elif bucket["rshape"]:
            print(f"OBSERVATION (inconclusive, <2 occurrences): reader shape: "
                  f"{bucket['rshape']}")
        if len(bucket["r5xx"]) >= 2:
            if alive():
                DEFECTS.append(
                    f"race window: {len(bucket['r5xx'])} x 5xx on telemetry "
                    f"reads while the collection lifecycle churned (200 "
                    f"always promised; no per-collection dependency) — "
                    f"Type3_RuntimeFailure — samples: {bucket['r5xx'][:3]}"
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
            print(f"ENV_ISSUES: transport hiccups during churn (liveness "
                  f"confirmed): {bucket['rtransport'][:3]}")

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
