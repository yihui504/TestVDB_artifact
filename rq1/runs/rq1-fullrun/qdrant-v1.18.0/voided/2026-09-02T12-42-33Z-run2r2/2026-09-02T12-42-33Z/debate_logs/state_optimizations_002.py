#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_optimizations_002
# strategy: count_consistency
# endpoint: collections+optimizations
# constraint_ids: qdrant_behavioral_collections_optimizations_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-optimizations
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 1 (CRUD-then-COUNT consistency, count readout =
  the queue-accounting summary of the optimizations face). The
  assertion pins a per-shard optimizer-status readout on every live
  collection; qdrant v1.18 materializes the status as
  result.summary{queued_optimizations, queued_segments, queued_points,
  idle_segments}. The STATE the summary counts is the set of persisted
  points awaiting optimization: when a wait=true upsert of K points has
  been ACKED, the queue accounting must drain to zero (queued_points
  -> 0, queued_optimizations -> 0) within the optimizer's normal cycle
  and then STAY drained (no further work arrives). A readout that
  never drains — or that re-queues phantom work — reports a state that
  never reconciles with the acknowledged writes (Type4). Every readout
  during the drain must stay HTTP 200 with the spec envelope (the
  status face must remain servable while the optimizer is actively
  indexing — no 5xx, no 4xx on a live collection).
  Legs (G4): (A baseline) fresh empty collection -> 200 + envelope;
  if summary present, queued_points is the integer 0 (nothing written
  yet). (B write) upsert K=150 distinct points wait=true (K ACKed).
  (C drain) poll the face every 1s up to a 75s budget; convergence =
  3 consecutive reads with summary present AND queued_points == 0 AND
  queued_optimizations == 0 (triple-read guards mid-transition
  samples). Every intermediate poll must be 200 + envelope-shaped.
  (D settled) two more reads 1s apart must still be idle (the drained
  state persists; a re-queued counter that wakes up again = phantom).
  Shape oracle per materialized response_shape (G5 typing): present
  groups must carry spec types (summary object with integer counters,
  running array, queued/completed/idle_segments array|null); unknown
  keys / absent optional groups = measured-only prints.
  [chunk_collections+optimizations coverage: count_consistency x
   qdrant_behavioral_collections_optimizations_001 (queue-accounting
   drain-to-idle after acked bulk write + channel stability while
   indexing)]
Oracle: after a wait=true upsert of K points the face returns only
  HTTP 200 responses whose result envelope obeys the materialized
  response_shape, and within a 75s budget 3 consecutive reads report
  summary.queued_points == 0 and queued_optimizations == 0, with two
  later reads still idle; a stuck queue (never idle by budget) or a
  re-awakened phantom queue after draining =
  Type4_StateLogicViolation; any non-200/5xx on the live collection
  with /healthz alive = Type3/Type4 per class.
"""

import os
import sys
import json
import time
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

# optimizations endpoint is not in the runtime PATHS whitelist — register
# it VERBATIM from raw_knowledge api_endpoints[].url:
#   {"path": "collections+optimizations", "method": "GET",
#    "url": "/collections/{collection_name}/optimizations"}
rt.PATHS["collection_optimizations"] = "/collections/{collection_name}/optimizations"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if 'optimizations' in k]}")
if rt.PATHS.get("collection_optimizations") != "/collections/{collection_name}/optimizations":
    print("VERDICT: SCRIPT_ERROR - optimizations URL registration failed")
    sys.exit(2)

DIM = 4
K = 150


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
    print(f"[liveness {tag}] healthz probe required")
    _hs, _hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={_hs} raw={str(_hraw)[:120]}")
    return _hs == 200


GROUPS = {"summary", "running", "queued", "completed", "idle_segments"}
SUMMARY_INTS = ("queued_optimizations", "queued_segments",
                "queued_points", "idle_segments")


def read_status(name, tag):
    """One GET optimizations; returns (kind, payload) where kind is
    'ok' (200 + envelope ok), 'shape' (200 + shape conflict),
    'non200' (non-200), 'transport' (s==0). payload carries detail."""
    s, raw = safe_request("GET", "collection_optimizations",
                          path_params={"collection_name": name})
    print(f"[{tag}] status={s} raw={str(raw)[:200]}")
    if s == 0:
        return "transport", raw
    if 500 <= s <= 599:
        return "non200", (s, raw)
    if s != 200:
        return "non200", (s, raw)
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return "shape", f"non-JSON 200 body: {str(raw)[:120]}"
    res = b.get("result") if isinstance(b, dict) else None
    if not isinstance(res, dict):
        return "shape", f"result not an object: {str(raw)[:150]}"
    for k in res:
        if k not in GROUPS:
            print(f"[{tag}] measured: extra result key {k!r}")
    v = res.get("summary")
    if v is not None and not isinstance(v, dict):
        return "shape", f"summary not an object: {v!r}"
    v = res.get("running")
    if v is not None and not isinstance(v, list):
        return "shape", f"running not an array: {v!r}"
    for k in ("queued", "completed", "idle_segments"):
        v = res.get(k)
        if v is not None and not isinstance(v, list):
            return "shape", f"{k} not array|null: {v!r}"
    summ = res.get("summary")
    if isinstance(summ, dict):
        for f in SUMMARY_INTS:
            fv = summ.get(f)
            if fv is not None and (not isinstance(fv, int)
                                   or isinstance(fv, bool)):
                return "shape", f"summary.{f} not an integer: {fv!r}"
    return "ok", (raw, res)


def is_idle(res):
    """True when the summary accounting reports zero queued work."""
    summ = res.get("summary") if isinstance(res, dict) else None
    if not isinstance(summ, dict):
        return None  # measured: no summary to judge
    qo = summ.get("queued_optimizations")
    qp = summ.get("queued_points")
    if not isinstance(qo, int) or isinstance(qo, bool):
        return None
    if not isinstance(qp, int) or isinstance(qp, bool):
        return None
    running = res.get("running")
    run_empty = (running is None) or (isinstance(running, list)
                                      and len(running) == 0)
    return (qo == 0 and qp == 0 and run_empty)


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    C = "sop2_" + TS + "_col"
    DEFECTS = []

    try:
        # ---- (A baseline) fresh empty collection ----
        a_s, a_raw = safe_request("PUT", "create_collection",
                                  path_params={"name": C},
                                  body={"vectors": {"size": DIM,
                                                    "distance": "Cosine"}})
        print(f"[A create] status={a_s} raw={a_raw[:150]}")
        if a_s not in (200, 201):
            print(f"SETUP_ERROR: create returned {a_s}")
            return "SCRIPT_ERROR"
        kind, payload = read_status(C, "A baseline")
        if kind == "transport":
            liveness("A")
            return "SCRIPT_ERROR"
        if kind == "non200":
            s, raw = payload
            if liveness("A"):
                DEFECTS.append(f"(A) baseline readout returned {s} on a "
                               f"fresh live collection — "
                               f"{'Type3_RuntimeFailure' if 500 <= s <= 599 else 'Type4_StateLogicViolation'} "
                               f"— raw={str(raw)[:150]}")
            else:
                return "SCRIPT_ERROR"
        elif kind == "shape":
            DEFECTS.append(f"(A) baseline 200 body shape conflict: "
                           f"{payload} — Type4_StateLogicViolation (spec wins)")
        else:
            _raw, res = payload
            idle = is_idle(res)
            if idle is False:
                DEFECTS.append(f"(A) fresh empty collection already reports "
                               f"queued work — phantom queue before any "
                               f"write — Type4_StateLogicViolation")
            elif idle is None:
                print("[A] measured: no summary accounting to judge baseline")

        # ---- (B write) wait=true upsert of K distinct points ----
        pts = [{"id": i, "vector": [float(i % 7) / 7.0, 0.2, 0.3, 0.4]}
               for i in range(K)]
        b_s, b_raw = safe_request("PUT", "upsert_points",
                                  path_params={"name": C},
                                  body={"points": pts},
                                  query_params={"wait": "true"})
        print(f"[B upsert {K}] status={b_s} raw={b_raw[:150]}")
        if b_s not in (200, 201):
            print(f"SETUP_ERROR: upsert returned {b_s} — cannot judge drain")
            return "SCRIPT_ERROR"

        # ---- (C drain) poll to idle within budget ----
        budget_s = 75.0
        deadline = time.time() + budget_s
        consec_idle = 0
        polls = 0
        drain_ok = False
        while time.time() < deadline:
            polls += 1
            kind, payload = read_status(C, f"C drain poll#{polls}")
            if kind == "transport":
                liveness("C")
                return "SCRIPT_ERROR"
            if kind == "non200":
                s, raw = payload
                if liveness("C"):
                    DEFECTS.append(f"(C) readout returned {s} while the "
                                   f"optimizer was indexing — "
                                   f"{'Type3_RuntimeFailure' if 500 <= s <= 599 else 'Type4_StateLogicViolation'} "
                                   f"— raw={str(raw)[:150]}")
                else:
                    return "SCRIPT_ERROR"
            elif kind == "shape":
                DEFECTS.append(f"(C) 200 body shape conflict during drain: "
                               f"{payload} — Type4_StateLogicViolation "
                               f"(spec wins)")
            else:
                _raw, res = payload
                idle = is_idle(res)
                if idle is None:
                    consec_idle = 0
                elif idle:
                    consec_idle += 1
                    if consec_idle >= 3:
                        drain_ok = True
                        break
                else:
                    consec_idle = 0
            time.sleep(1.0)
        if not drain_ok:
            if liveness("C"):
                DEFECTS.append(f"(C) queue accounting never drained to idle "
                               f"within {int(budget_s)}s after {polls} polls "
                               f"— {K} acked points stayed queued — "
                               f"Type4_StateLogicViolation (readout reports "
                               f"a state that never reconciles with acked "
                               f"writes)")
            else:
                return "SCRIPT_ERROR"

        # ---- (D settled) idle state persists ----
        for i in range(2):
            time.sleep(1.0)
            kind, payload = read_status(C, f"D settled#{i}")
            if kind == "transport":
                liveness("D")
                return "SCRIPT_ERROR"
            if kind == "non200":
                s, raw = payload
                if liveness("D"):
                    DEFECTS.append(f"(D) readout returned {s} after drain — "
                                   f"{'Type3_RuntimeFailure' if 500 <= s <= 599 else 'Type4_StateLogicViolation'} "
                                   f"— raw={str(raw)[:150]}")
                else:
                    return "SCRIPT_ERROR"
            elif kind == "shape":
                DEFECTS.append(f"(D) 200 body shape conflict after drain: "
                               f"{payload} — Type4_StateLogicViolation")
            else:
                _raw, res = payload
                idle = is_idle(res)
                if idle is False:
                    DEFECTS.append(f"(D) queue accounting re-awoke with "
                                   f"queued work after having drained — "
                                   f"phantom re-queue — "
                                   f"Type4_StateLogicViolation")

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
    except Exception:
        import traceback
        traceback.print_exc()
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
