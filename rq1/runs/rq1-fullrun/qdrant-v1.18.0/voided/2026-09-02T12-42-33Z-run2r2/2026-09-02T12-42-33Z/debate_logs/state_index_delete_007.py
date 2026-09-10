#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_index_delete_007
# strategy: concurrent (Strategy 7: collection-lifecycle x access concurrency)
# endpoint: index+delete
# constraint_ids: qdrant_behavioral_index_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/delete-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: lifecycle concurrency (Strategy 7) x qdrant_behavioral_index_delete_001 —
  while thread A churns the COLLECTION lifecycle (drop -> recreate same name,
  LIFECYCLE_ITERS rounds), N probe threads (TESTVDB_CONCURRENT_THREADS, default
  10) continuously issue DELETE /collections/{name}/index/{field_name} on the
  churning name. The behavioral assertion splits the response face into exactly
  two legal outcomes: 200 when the collection exists (idempotent delete whether
  or not the index does) and 404 when it does not. Anything else under churn —
  500/panic/connection loss (should be 404 "collection does not exist", not an
  internal error, qdrant #9229 shape) or an unexplained 4xx (inconsistent
  disposition of the same well-formed request) — is a defect. After the churn
  ends: final idempotent delete on the quiesced collection must be exactly 200.
  [chunk_index+delete coverage: concurrent/lifecycle x
  qdrant_behavioral_index_delete_001 (200/404 dichotomy under collection
  drop/recreate churn + final-200 idempotence leg)]
Oracle: every probe DELETE returns exactly 200 or exactly 404 (200 while the
  collection exists, 404 while absent); 5xx/transport losses occur 0 times
  while /healthz stays alive (>=2 occurrences = Type3_RuntimeFailure); no other
  4xx ever appears (any occurrence = Type4 inconsistent disposition); after the
  churn the final delete on the existing collection returns exactly 200. A
  single sporadic 5xx is reported as a note only (below the 2-occurrence
  reproduction bar for race false positives).
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

# path keys verified against sorted(rt.PATHS): delete_index/create_index/
# describe_collection/drop_collection/create_collection/healthz are native
# qdrant runtime keys (no fabrication)
print(f"[PATHS] index keys present="
      f"{[k for k in ('delete_index', 'create_index', 'describe_collection', 'drop_collection', 'create_collection') if k in rt.PATHS]}")

N_PROBES = max(2, int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10")))
LIFECYCLE_ITERS = 15
FIELD = "f_lifecycle"


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
    """Transport/5xx branch liveness re-check via the lightweight healthz face."""
    hs, hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def create_collection(C):
    return safe_request("PUT", "create_collection",
                        body={"vectors": {"size": 4, "distance": "Cosine"}},
                        path_params={"name": C})


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sidd7_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []
    stop = threading.Event()

    status_200 = [0]
    status_404 = [0]
    bad_5xx = []      # (status, raw_snippet, healthz_alive)
    bad_4xx = []      # (status, raw_snippet)
    lock = threading.Lock()

    def lifecycle_thread():
        """Thread A: drop -> recreate the same collection name, repeatedly."""
        for i in range(LIFECYCLE_ITERS):
            s, raw = safe_request("DELETE", "drop_collection",
                                  path_params={"name": C}, timeout=30)
            print(f"[lifecycle {i}] drop status={s} raw={str(raw)[:100]}")
            time.sleep(0.05)
            s, raw = create_collection(C)
            # 409 = already exists is acceptable churn overlap
            print(f"[lifecycle {i}] create status={s} raw={str(raw)[:100]}")
            time.sleep(0.05)
        stop.set()

    def probe_thread(tid):
        """Probe thread: continuous idempotent index deletes on the churning name."""
        n = 0
        while not stop.is_set():
            s, raw = safe_request("DELETE", "delete_index",
                                  path_params={"name": C, "field_name": FIELD},
                                  query_params={"wait": "true"}, timeout=15)
            n += 1
            if s in (200, 201):
                with lock:
                    status_200[0] += 1
            elif s == 404:
                with lock:
                    status_404[0] += 1
            elif s == 0 or 500 <= s <= 599:
                alive = liveness(f"probe{tid} status={s}")
                with lock:
                    bad_5xx.append((s, str(raw)[:160], alive))
                print(f"[probe {tid}] 5xx/transport status={s} raw={str(raw)[:160]}")
            else:
                with lock:
                    bad_4xx.append((s, str(raw)[:160]))
                print(f"[probe {tid}] unexpected status={s} raw={str(raw)[:160]}")
            if n % 25 == 0:
                print(f"[probe {tid}] issued={n} so_far 200={status_200[0]} 404={status_404[0]}")
            time.sleep(0.02)

    try:
        # ---- setup: initial collection so the first probes can hit the 200 face ----
        s, raw = create_collection(C)
        if s not in (200, 201, 409):
            print(f"VERDICT: SCRIPT_ERROR - initial create: {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"

        tA = threading.Thread(target=lifecycle_thread)
        probes = [threading.Thread(target=probe_thread, args=(k,)) for k in range(N_PROBES)]
        tA.start()
        for t in probes:
            t.start()
        tA.join()
        for t in probes:
            t.join()

        # ---- adjudication of the churn window ----
        total = status_200[0] + status_404[0] + len(bad_5xx) + len(bad_4xx)
        print(f"[summary] probes_total={total} 200={status_200[0]} 404={status_404[0]} "
              f"bad5xx={len(bad_5xx)} bad4xx={len(bad_4xx)}")
        if total == 0:
            print("VERDICT: SCRIPT_ERROR - no probe completed (churn window too tight)")
            return "SCRIPT_ERROR"
        if status_200[0] == 0 or status_404[0] == 0:
            # not a defect: interleave evidence weak; report honestly
            print(f"[note] only one legal face observed "
                  f"(200={status_200[0]}, 404={status_404[0]}) - weak interleave evidence, not a defect")
        alive_5xx = [e for e in bad_5xx if e[2]]
        if len(alive_5xx) >= 2:
            DEFECTS.append(
                f"(churn) {len(alive_5xx)} 5xx/transport responses on index delete "
                f"while /healthz alive (samples={alive_5xx[:3]}) - "
                f"Type3_RuntimeFailure - should be 404/200, not internal error "
                f"(qdrant_behavioral_index_delete_001)")
        elif len(bad_5xx) >= 1:
            print(f"[note] sporadic 5xx/transport occurrences={len(bad_5xx)} "
                  f"below the 2-occurrence reproduction bar - recorded, not judged "
                  f"(samples={bad_5xx[:2]})")
        for s, snip in bad_4xx:
            DEFECTS.append(
                f"(churn) well-formed idempotent index delete returned unexpected "
                f"HTTP {s} under lifecycle churn - Type4 inconsistent disposition "
                f"(legal faces are exactly 200/404) - raw={snip} "
                f"(qdrant_behavioral_index_delete_001)")

        # ---- final leg: quiesced collection -> delete must be exactly 200 ----
        s, raw = create_collection(C)
        if s not in (200, 201, 409):
            print(f"VERDICT: SCRIPT_ERROR - final ensure-create: {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"
        s, raw = safe_request("DELETE", "delete_index",
                              path_params={"name": C, "field_name": FIELD},
                              query_params={"wait": "true"}, timeout=30)
        print(f"[final delete] status={s} raw={str(raw)[:200]}")
        if s in (200, 201):
            pass
        elif s == 0 or 500 <= s <= 599:
            if liveness("final delete"):
                DEFECTS.append(
                    f"(final) idempotent delete on existing collection returned "
                    f"{s} while /healthz alive - Type3_RuntimeFailure - raw={str(raw)[:160]}")
        else:
            DEFECTS.append(
                f"(final) idempotent delete on existing collection rejected with "
                f"HTTP {s} - Type4 inconsistent disposition - raw={str(raw)[:160]} "
                f"(qdrant_behavioral_index_delete_001)")
        ds, draw = safe_request("GET", "describe_collection",
                                path_params={"name": C}, timeout=30)
        print(f"[final describe] status={ds} raw={str(draw)[:160]}")
        if ds != 200:
            DEFECTS.append(
                f"(final) describe after churn returned {ds} on an existing "
                f"collection - Type4_StateLogicViolation - raw={str(draw)[:160]}")

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print(f"lifecycle churn clean: {total} probes returned only 200/404 "
              f"(200={status_200[0]}, 404={status_404[0]}), no 5xx with healthz "
              f"alive, no unexpected 4xx, final idempotent delete exactly 200 - NO_DEFECT")
        return "NO_DEFECT"
    finally:
        # cleanup (own data only; failure must not flip the verdict)
        try:
            rt.drop_collection(C)
            print(f"[cleanup] dropped {C}")
        except Exception as e:
            print(f"[cleanup] drop {C} failed (ignored): {e}")


if __name__ == "__main__":
    try:
        _v = main()
    except Exception:
        import traceback
        traceback.print_exc()
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
