#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_optimizations_003
# strategy: upsert_idempotence
# endpoint: collections+optimizations
# constraint_ids: qdrant_behavioral_collections_optimizations_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-optimizations
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 3 (upsert idempotence) read out through the
  optimizer-status face (collections+optimizations) with the describe
  face (collections+get, PATHS describe_collection) as the count
  anchor. Upsert in qdrant is idempotent per id: replaying the SAME
  K ids must not grow the stored point set (points_count stays K, not
  2K) and must not leave phantom queued work behind. Two readouts are
  judged after each stage:
    - optimizations summary queue accounting: after each wait=true
      stage the face must DRAIN to idle (3 consecutive reads with
      summary.queued_points == 0 and queued_optimizations == 0) —
      a second replay of identical ids must not permanently re-queue
      phantom work that never settles;
    - describe points_count (cross-face state anchor, G9): after the
      duplicate replay and drain, points_count must be exactly K — a
      2K readout means the replay duplicated stored points (upsert
      idempotence broken) or the storage counter double-counted;
      null is shape-legal on describe and logged measured-only.
  Legs (G6-mutated sequence): (A) create; (B) upsert K=120 distinct
    ids wait=true; (C) drain to idle (75s budget); (D) REPLAY the same
    120 ids wait=true — the duplication mutation is the one that most
    easily breaks a buggy idempotence path into a doubled store; (E)
    drain to idle again (the queue must settle a second time, so a
    stuck readout after replays is caught); (F) describe points_count
    anchor == K.
  Every optimizations readout in the drain legs must be HTTP 200 with
  the spec-typed result envelope (materialized response_shape: result
  object; summary object with integer counters; running array;
  queued/completed/idle_segments array|null; conflict zones
  measured-only).
  [chunk_collections+optimizations coverage: upsert_idempotence x
   qdrant_behavioral_collections_optimizations_001 (duplicate-id
   replay: drain-to-idle twice + points_count anchor)]
Oracle: after each wait=true stage the optimizations face drains to 3
  consecutive idle reads (queued_points == 0, queued_optimizations ==
  0) within a 75s budget, and after the duplicate replay describe
  reports points_count == K (120) — an integer 240 at stage F =
  Type4_StateLogicViolation (duplicated store or double-counted
  readout); queue never drained after either stage or phantom
  re-queue = Type4; any present group typed against the spec wrongly
  = Type4 shape conflict; 5xx/non-200 on the live collection with
  /healthz alive = Type3/Type4 per class.
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
K = 120


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
    """Returns (kind, payload): kind in {ok, shape, non200, transport};
    ok payload = (raw, result_dict)."""
    s, raw = safe_request("GET", "collection_optimizations",
                          path_params={"collection_name": name})
    print(f"[{tag}] status={s} raw={str(raw)[:200]}")
    if s == 0:
        return "transport", raw
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
    summ = res.get("summary") if isinstance(res, dict) else None
    if not isinstance(summ, dict):
        return None
    qo = summ.get("queued_optimizations")
    qp = summ.get("queued_points")
    if (not isinstance(qo, int) or isinstance(qo, bool)
            or not isinstance(qp, int) or isinstance(qp, bool)):
        return None
    running = res.get("running")
    run_empty = (running is None) or (isinstance(running, list)
                                      and len(running) == 0)
    return qo == 0 and qp == 0 and run_empty


def drain_to_idle(name, tag, defects, budget_s=75.0):
    """Poll until 3 consecutive idle reads. Records defects for non-200 /
    shape conflicts; returns True when drained, None on env abort."""
    deadline = time.time() + budget_s
    consec = 0
    polls = 0
    while time.time() < deadline:
        polls += 1
        kind, payload = read_status(name, f"{tag} poll#{polls}")
        if kind == "transport":
            liveness(tag)
            return None
        if kind == "non200":
            s, raw = payload
            if liveness(tag):
                defects.append(f"({tag}) readout returned {s} — "
                               f"{'Type3_RuntimeFailure' if 500 <= s <= 599 else 'Type4_StateLogicViolation'} "
                               f"— raw={str(raw)[:150]}")
                return True
            return None
        if kind == "shape":
            defects.append(f"({tag}) 200 body shape conflict: {payload} — "
                           f"Type4_StateLogicViolation (spec wins)")
            return True
        _raw, res = payload
        idle = is_idle(res)
        if idle is None:
            consec = 0
        elif idle:
            consec += 1
            if consec >= 3:
                return True
        else:
            consec = 0
        time.sleep(1.0)
    if liveness(tag):
        defects.append(f"({tag}) queue accounting never drained to idle "
                       f"within {int(budget_s)}s after {polls} polls — "
                       f"Type4_StateLogicViolation (readout reports a state "
                       f"that never reconciles with acked writes)")
        return True
    return None


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    C = "sop3_" + TS + "_col"
    DEFECTS = []

    try:
        # ---- (A) create ----
        a_s, a_raw = safe_request("PUT", "create_collection",
                                  path_params={"name": C},
                                  body={"vectors": {"size": DIM,
                                                    "distance": "Cosine"}})
        print(f"[A create] status={a_s} raw={a_raw[:150]}")
        if a_s not in (200, 201):
            print(f"SETUP_ERROR: create returned {a_s}")
            return "SCRIPT_ERROR"

        # ---- (B) first write: K distinct ids, wait=true ----
        pts = [{"id": i, "vector": [float(i % 7) / 7.0, 0.2, 0.3, 0.4]}
               for i in range(K)]
        b_s, b_raw = safe_request("PUT", "upsert_points",
                                  path_params={"name": C},
                                  body={"points": pts},
                                  query_params={"wait": "true"})
        print(f"[B upsert {K} distinct] status={b_s} raw={b_raw[:150]}")
        if b_s not in (200, 201):
            print(f"SETUP_ERROR: first upsert returned {b_s}")
            return "SCRIPT_ERROR"

        # ---- (C) drain to idle after first write ----
        r = drain_to_idle(C, "C drain#1", DEFECTS)
        if r is None:
            return "SCRIPT_ERROR"

        # ---- (D) duplicate-id replay: SAME K ids, wait=true ----
        d_s, d_raw = safe_request("PUT", "upsert_points",
                                  path_params={"name": C},
                                  body={"points": pts},
                                  query_params={"wait": "true"})
        print(f"[D replay same {K} ids] status={d_s} raw={d_raw[:150]}")
        if d_s not in (200, 201):
            print(f"SETUP_ERROR: replay upsert returned {d_s}")
            return "SCRIPT_ERROR"

        # ---- (E) drain to idle after replay ----
        r = drain_to_idle(C, "E drain#2", DEFECTS)
        if r is None:
            return "SCRIPT_ERROR"

        # ---- (F) describe points_count anchor: must be K, not 2K ----
        f_s, f_raw = safe_request("GET", "describe_collection",
                                  path_params={"name": C})
        print(f"[F describe] status={f_s} raw={f_raw[:250]}")
        if f_s != 200:
            print(f"SETUP_ERROR: describe returned {f_s} — count anchor "
                  f"unavailable")
            return "SCRIPT_ERROR"
        try:
            pc = json.loads(f_raw)["result"].get("points_count")
        except Exception:
            pc = None
        if pc is None:
            print("[F] measured: points_count null/absent — shape-legal on "
                  "describe — count anchor not judged")
        elif isinstance(pc, bool) or not isinstance(pc, int):
            DEFECTS.append(f"(F) points_count={pc!r} is not an integer — "
                           f"Type4_StateLogicViolation")
        elif pc != K:
            DEFECTS.append(f"(F) after replaying the same {K} ids twice with "
                           f"wait=true, points_count={pc} != {K} — the "
                           f"duplicate replay duplicated the stored point "
                           f"set (upsert idempotence broken) — "
                           f"Type4_StateLogicViolation — raw={f_raw[:200]}")
        else:
            print(f"[F] OK: points_count == {K} after duplicate replay")

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
