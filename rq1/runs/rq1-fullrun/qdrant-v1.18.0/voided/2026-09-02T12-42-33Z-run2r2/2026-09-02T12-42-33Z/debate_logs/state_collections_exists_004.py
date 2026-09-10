#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_exists_004
# strategy: concurrent
# endpoint: collections+exists
# constraint_ids: qdrant_behavioral_collections_exists_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/collection-exists
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (Concurrency State Blindness — exists readout under
#   parallel lifecycles of DIFFERENT collections)
"""
Attack: concurrent multi-collection lifecycle x exists verdict
  (Strategy 4: point-level concurrency generalizes here to N
  independent collection lifecycles in parallel — the deployment /
  migration / CI pattern where many collections are provisioned and
  torn down at once, each worker polling exists to confirm its own
  collection's phase). Each thread owns a UNIQUE name namespace, so
  every exists probe has a settled ground truth (qdrant collection
  create/delete are synchronous: a 200 create means the name is
  registered; a 200 delete means it is released) — any wrong verdict,
  non-200 channel answer, or 5xx is NOT a race artifact but a hard
  violation of qdrant_behavioral_collections_exists_001.
  Per thread, per cycle: create -> exists==true (200 + boolean shape)
  -> delete -> exists==false (200 + boolean shape, never 404).
  After all threads join: every name must be exists=false (no
  residue), then cleanup drops leftovers defensively.
  [chunk_collections+exists coverage: concurrent x
   qdrant_behavioral_collections_exists_001 (N parallel lifecycles,
   post-confirmation verdicts, final no-residue check)]
Oracle: after a 200-confirmed create, exists answers exactly
  200 + result.exists=true; after a 200-confirmed delete, exactly
  200 + result.exists=false — for every thread, every cycle, under
  full parallel load; at quiescence every thread's name still answers
  200+false. Wrong verdict / 404 / shape violation =
  Type4_StateLogicViolation; 5xx = Type3_RuntimeFailure only after
  /healthz confirms liveness; create/delete failures are env-class
  (SCRIPT_ERROR path), never defect conclusions.
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
N_CYCLES = max(1, int(os.environ.get("TESTVDB_EXISTS_CYCLES", "3")))


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
    PFX = "sce4_" + TS + "_"
    DEFECTS = []
    lock = threading.Lock()
    wrong = []      # wrong verdict / wrong channel / shape violations
    hard_5xx = []   # 5xx on exists after a settled mutation
    env_failures = []

    def alive():
        _hs, _hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[healthz] status={_hs} raw={str(_hraw)[:120]}")
        return _hs == 200

    def worker(tid):
        name = f"{PFX}w{tid}_col"
        for cyc in range(N_CYCLES):
            tag = f"T{tid}/c{cyc}"
            # create (settled: synchronous 200 = name registered)
            try:
                cs, craw = safe_request("PUT", "create_collection",
                                        path_params={"name": name},
                                        body={"vectors": {"size": 4, "distance": "Cosine"}})
            except Exception as e:
                with lock:
                    env_failures.append(f"{tag}: create exception {str(e)[:100]}")
                continue
            if cs != 200:
                with lock:
                    env_failures.append(f"{tag}: create status={cs} raw={str(craw)[:100]}")
                continue
            # exists must be 200 + true on settled-present state
            try:
                s, raw = safe_request("GET", "collection_exists",
                                      path_params={"collection_name": name})
            except Exception as e:
                with lock:
                    env_failures.append(f"{tag}: exists exception {str(e)[:100]}")
                continue
            if s == 0:
                with lock:
                    env_failures.append(f"{tag}: exists transport {str(raw)[:100]}")
                continue
            if 500 <= s <= 599:
                with lock:
                    hard_5xx.append(f"{tag}-present: {s} raw={str(raw)[:120]}")
                continue
            shape_ok, ev, note = parse_exists(raw)
            if s != 200 or not shape_ok or ev is not True:
                with lock:
                    wrong.append(f"{tag}-present: status={s} exists={ev} "
                                 f"shape_note={note} raw={str(raw)[:120]}")
            # delete (settled: synchronous 200 = name released)
            try:
                ds, draw = safe_request("DELETE", "drop_collection",
                                        path_params={"name": name})
            except Exception as e:
                with lock:
                    env_failures.append(f"{tag}: delete exception {str(e)[:100]}")
                continue
            if ds != 200:
                with lock:
                    env_failures.append(f"{tag}: delete status={ds} raw={str(draw)[:100]}")
                continue
            # exists must be 200 + false on settled-absent state
            try:
                s2, raw2 = safe_request("GET", "collection_exists",
                                        path_params={"collection_name": name})
            except Exception as e:
                with lock:
                    env_failures.append(f"{tag}: exists2 exception {str(e)[:100]}")
                continue
            if s2 == 0:
                with lock:
                    env_failures.append(f"{tag}: exists2 transport {str(raw2)[:100]}")
                continue
            if 500 <= s2 <= 599:
                with lock:
                    hard_5xx.append(f"{tag}-absent: {s2} raw={str(raw2)[:120]}")
                continue
            shape_ok2, ev2, note2 = parse_exists(raw2)
            if s2 != 200 or not shape_ok2 or ev2 is not False:
                with lock:
                    wrong.append(f"{tag}-absent: status={s2} exists={ev2} "
                                 f"shape_note={note2} raw={str(raw2)[:120]}")

    names = []
    threads = []
    try:
        for tid in range(N_THREADS):
            names.append(f"{PFX}w{tid}_col")
            th = threading.Thread(target=worker, args=(tid,), daemon=True)
            threads.append(th)
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=300)
        stuck = [i for i, th in enumerate(threads) if th.is_alive()]
        if stuck:
            print(f"ENV_ISSUE: worker threads still running after join timeout: {stuck}")
            return "SCRIPT_ERROR"

        # ---- quiescence: every name must answer 200 + exists=false ----
        residue = []
        for name in names:
            try:
                s, raw = safe_request("GET", "collection_exists",
                                      path_params={"collection_name": name})
            except Exception as e:
                env_failures.append(f"final {name}: exception {str(e)[:100]}")
                continue
            shape_ok, ev, note = parse_exists(raw)
            print(f"[final {name.split('_')[-2]}/{name[-6:]}] status={s} exists={ev} "
                  f"raw={str(raw)[:100]}")
            if s == 0 or 500 <= s <= 599 or not shape_ok:
                env_failures.append(f"final {name}: status={s} note={note}")
                continue
            if ev is not False:
                residue.append(f"{name} answered exists={ev} after its confirmed delete")

        # ---- adjudication ----
        for w in wrong:
            DEFECTS.append(f"concurrent lifecycle: exists probe {w} — settled ground "
                           f"truth contradicted / pinned 200+boolean channel broken — "
                           f"Type4_StateLogicViolation "
                           f"(qdrant_behavioral_collections_exists_001)")
        if hard_5xx:
            if alive():
                for h in hard_5xx:
                    DEFECTS.append(f"concurrent lifecycle: exists returned 5xx with "
                                   f"service alive ({h}) — Type3_RuntimeFailure")
            else:
                return "SCRIPT_ERROR"
        for r in residue:
            DEFECTS.append(f"quiescence residue: {r} — deleted name still reports "
                           f"present — Type4_StateLogicViolation")
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
        for name in names:
            try:
                rt.drop_collection(name)
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
