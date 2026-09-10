#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_delete_004
# strategy: lifecycle_concurrency
# endpoint: collections+delete
# constraint_ids: qdrant_behavioral_collections_delete_001, qdrant_bc_delete_invisibility_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 Concurrency State Blindness
"""
Attack: lifecycle-vs-access concurrency for collections+delete
  (collections+delete; URLs from raw_knowledge api_endpoints[].url).
  Strategy-7 shape (collection-level lifecycle racing access, NOT
  point-level concurrency): thread L cycles DELETE /collections/{name}
  -> recreate (same name) 6 times while K access threads (K =
  TESTVDB_CONCURRENT_THREADS, default 10) hammer the count face.
  G6 mutation justification: delete/recreate of the NAME is the most
  destructive lifecycle mutation — every access lands on a state where
  the collection is (a) present, (b) absent mid-delete, or (c) freshly
  recreated; the invariant under fire is that absence is always served
  as 404 and presence as 200, never as an internal error.
  Judgment (G5/G8): count answering 500 while the service is alive =
  Type3_RuntimeFailure (should be 404 "collection does not exist" /
  200); sporadic single 500s are only reported when observed >= 2
  times (race false-positive rule); 404/200 mixes are correct
  semantics, not defects; transport failures re-checked via /healthz
  before any conclusion. Final reconciliation (Type4): describe and
  count faces must agree on the end state (200<->200, 404<->404).
  [chunk_collections+delete coverage: lifecycle_concurrency x
   qdrant_behavioral_collections_delete_001 +
   qdrant_bc_delete_invisibility_001 (delete/recreate racing the
   count face)]
Oracle: during the race, count only ever returns 200 or 404 (>=2
  occurrences of 500 with /healthz alive = Type3_RuntimeFailure);
  after the race, describe status == count status (200<->200 or
  404<->404; mismatch = Type4_StateLogicViolation); /healthz dead =
  SCRIPT_ERROR (environment, not defect).
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

K_THREADS = max(1, int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10") or "10"))
CYCLES = 6
ACCESS_ROUNDS = 15
VEC_CFG = {"vectors": {"size": 4, "distance": "Cosine"}}


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def parse_json(raw):
    try:
        b = json.loads(raw) if raw else None
        return b if isinstance(b, dict) else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scdl4_" + TS + "_"
    C = PFX + "race"
    DEFECTS = []

    # tallies (no list.remove; dict counters only)
    status_tally = {}
    samples_500 = []
    samples_transport = []
    thread_errors = []
    lock = threading.Lock()

    def note(status, raw):
        with lock:
            status_tally[status] = status_tally.get(status, 0) + 1
            if 500 <= status <= 599 and len(samples_500) < 3:
                samples_500.append((status, (raw or "")[:160]))
            if status == 0 and len(samples_transport) < 3:
                samples_transport.append((status, (raw or "")[:160]))

    def lifecycle_thread():
        for _ in range(CYCLES):
            try:
                ds, draw = safe_request("DELETE", "drop_collection",
                                        path_params={"name": C})
                note(ds, draw)  # 200 or 404 both fine mid-race
                time.sleep(0.05)
                cs, craw = safe_request("PUT", "create_collection",
                                        path_params={"name": C}, body=VEC_CFG)
                note(cs, craw)  # 200 or transient 404-race both fine
                time.sleep(0.05)
            except Exception as e:  # defensive: thread must never die silently
                with lock:
                    thread_errors.append(f"lifecycle: {type(e).__name__}: {e}")

    def access_thread(tid):
        for _ in range(ACCESS_ROUNDS):
            try:
                s, raw = safe_request("POST", "count", path_params={"name": C},
                                      body={"exact": True})
                note(s, raw)
            except Exception as e:
                with lock:
                    thread_errors.append(f"access[{tid}]: {type(e).__name__}: {e}")
            time.sleep(0.02)

    try:
        # ---- setup: collection exists before the race ----
        cr_s, cr_raw = safe_request("PUT", "create_collection", path_params={"name": C},
                                    body=VEC_CFG)
        print(f"[setup create] status={cr_s} raw={cr_raw[:160]}")
        if cr_s not in (200, 201):
            print("SETUP_ERROR: initial create failed — cannot run lifecycle race")
            return "SCRIPT_ERROR"

        # ---- race: 1 lifecycle thread + K access threads ----
        print(f"[race] lifecycle cycles={CYCLES}; access threads={K_THREADS} "
              f"x rounds={ACCESS_ROUNDS}")
        threads = [threading.Thread(target=lifecycle_thread)]
        for i in range(K_THREADS):
            threads.append(threading.Thread(target=access_thread, args=(i,)))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        tally_str = json.dumps({str(k): v for k, v in sorted(status_tally.items())})
        print(f"[race tally] {tally_str}")
        for st, sraw in samples_500:
            print(f"[sample 5xx] status={st} raw={sraw}")
        for st, traw in samples_transport:
            print(f"[sample transport] status={st} raw={traw}")
        if thread_errors:
            for e in thread_errors[:5]:
                print(f"[thread error] {e}")

        # ---- G8: liveness re-check before any Type3 conclusion ----
        h_s, h_raw = safe_request("GET", "healthz", timeout=10)
        print(f"[liveness post-race] healthz status={h_s} raw={str(h_raw)[:120]}")
        if h_s != 200:
            print("SCRIPT_ERROR: service unhealthy after race — environment, not defect")
            return "SCRIPT_ERROR"

        n_500 = sum(v for k, v in status_tally.items() if isinstance(k, int) and 500 <= k <= 599)
        if n_500 >= 2:
            DEFECTS.append(f"(race) count/create/delete faces returned 5xx {n_500} "
                           f"times during delete/recreate cycling with /healthz "
                           f"alive (>=2 reproduction threshold) — should be 404/200, "
                           f"never internal error — Type3_RuntimeFailure — samples="
                           f"{samples_500} (BS-03; qdrant_behavioral_collections_"
                           f"delete_001 / qdrant_bc_delete_invisibility_001)")
        elif n_500 == 1:
            print("NOTE: single sporadic 5xx observed (<2 threshold) — recorded, "
                  "not reported as a defect per race false-positive rule")
        n_transport = status_tally.get(0, 0)
        if n_transport:
            print(f"NOTE: {n_transport} transport failures mid-race with /healthz "
                  f"alive at end — transient under concurrency, not judged a defect")

        # ---- final reconciliation (Type4): faces must agree on end state ----
        time.sleep(0.5)
        fd_s, fd_raw = safe_request("GET", "describe_collection", path_params={"name": C})
        fc_s, fc_raw = safe_request("POST", "count", path_params={"name": C},
                                    body={"exact": True})
        print(f"[final describe] status={fd_s} raw={fd_raw[:160]}")
        print(f"[final count] status={fc_s} raw={fc_raw[:160]}")
        if fd_s == 200 and fc_s == 404:
            DEFECTS.append(f"(final) describe says present (200) but count says "
                           f"absent (404) after lifecycle race — face disagreement — "
                           f"Type4_StateLogicViolation")
        if fd_s == 404 and fc_s == 200:
            DEFECTS.append(f"(final) describe says absent (404) but count says "
                           f"present (200) after lifecycle race — face disagreement — "
                           f"Type4_StateLogicViolation")
        if fd_s == 0 or fc_s == 0 or 500 <= fd_s <= 599 or 500 <= fc_s <= 599:
            _hs2, _hraw2 = safe_request("GET", "healthz", timeout=10)
            print(f"[liveness final] healthz status={_hs2} raw={str(_hraw2)[:120]}")
            if _hs2 != 200:
                return "SCRIPT_ERROR"
            DEFECTS.append(f"(final) reconciliation probe returned describe={fd_s} "
                           f"count={fc_s} with service alive — Type3_RuntimeFailure")

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
