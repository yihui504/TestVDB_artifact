#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_batch_payload_order_002
# strategy: transaction
# endpoint: points+batch
# constraint_ids: qdrant_state_points_batch_001
# source_url: https://qdrant.tech/documentation/manage-data/points/
# doc_version: current (site latest; no version archive)
"""
Attack: sequence-order semantics at PAYLOAD granularity (transaction
  strategy, order face) x qdrant_state_points_batch_001 "batch operations
  are applied sequentially in the order given". Five two-op batches pair
  payload mutations whose FINAL payload differs depending on which op ran
  last, so any reordering/parallel application inside the batch is visible
  in readback: (B1) set+set accumulates both keys; (B2) set then
  overwrite_payload -> ONLY the overwrite payload survives (overwrite
  later must wipe the earlier set); (B3) overwrite then set -> BOTH keys
  (overwrite first, set lands after); (B4) set then clear_payload -> {}
  (clear later wipes everything); (B5) clear then set -> the set payload
  survives. Last-writer-wins IN THE GIVEN ORDER is the oracle for every
  phase. Persistence is judged via point readback (get with payload), not
  via the response alone.
  [chunk_points+batch coverage: transaction/order x
  qdrant_state_points_batch_001 (set/set + set/overwrite +
  overwrite/set + set/clear + clear/set ordering chains)]
Oracle: after each 200 batch the point payload readback must deep-equal
  (type-strict) exactly: B1 {"seed":0,"p1":"a","p2":"b"}; B2 {"only":"z"};
  B3 {"base":"y","late":"w"}; B4 {}; B5 {"after":true}. Any payload that
  contradicts last-writer-wins-in-given-order (e.g. B2 retaining p3, B3
  missing "late", B4 retaining keys, B5 empty) = Type4_StateLogicViolation
  (order violation, qdrant_state_points_batch_001); 200 batch with
  len(result) != len(operations) = Type4 per-op-results violation; 5xx
  with /healthz alive = Type3_RuntimeFailure; transport failure ->
  liveness re-check before any verdict.
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

# points+batch registered VERBATIM from raw_knowledge api_endpoints[]:
#   {"path": "points+batch", "method": "POST",
#    "url": "/collections/{collection_name}/points/batch"}
rt.PATHS["batch_update"] = "/collections/{collection_name}/points/batch"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if k == 'batch_update']}")

DEFECTS = []
ABORT = [False]


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
    print(f"[liveness {tag}] healthz probe required")
    _hs, _hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={_hs} raw={str(_hraw)[:120]}")
    return _hs == 200


def result_of(raw):
    try:
        return json.loads(raw).get("result")
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        return None


def type_strict_eq(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return type(a) is type(b) and a == b
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return (set(a.keys()) == set(b.keys())
                and all(type_strict_eq(a[k], b[k]) for k in a))
    if isinstance(a, list):
        return (len(a) == len(b)
                and all(type_strict_eq(x, y) for x, y in zip(a, b)))
    return a == b


def run_batch(tag, coll, ops):
    s, raw = safe_request("POST", "batch_update",
                          path_params={"collection_name": coll},
                          body={"operations": ops},
                          query_params={"wait": "true"})
    print(f"[{tag} batch {len(ops)} ops] status={s} raw={str(raw)[:240]}")
    if s == 0:
        if not liveness(tag):
            ABORT[0] = True
        else:
            DEFECTS.append(f"({tag}) batch transport failure with service "
                           f"alive — Type3_RuntimeFailure")
        return s
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) batch returned {s} with service alive "
                           f"— Type3_RuntimeFailure — raw={str(raw)[:150]}")
        else:
            ABORT[0] = True
        return s
    if s == 200:
        res = result_of(raw)
        if not isinstance(res, list):
            DEFECTS.append(f"({tag}) 200 batch result is not an array — "
                           f"raw={str(raw)[:200]} — Type4_StateLogicViolation")
        elif len(res) != len(ops):
            DEFECTS.append(f"({tag}) 200 batch returned {len(res)} result "
                           f"entries for {len(ops)} operations — "
                           f"Type4_StateLogicViolation")
    return s


def readback(tag, coll, pid, expected):
    s, raw = safe_request("GET", "get_point",
                          path_params={"name": coll, "point_id": pid},
                          query_params={"with_payload": "true"})
    print(f"[{tag} get {pid}] status={s} raw={str(raw)[:220]}")
    if s == 0:
        if not liveness(tag):
            ABORT[0] = True
        return False
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) GET returned {s} with service alive — "
                           f"Type3_RuntimeFailure")
        else:
            ABORT[0] = True
        return False
    if s != 200:
        DEFECTS.append(f"({tag}) GET {pid} returned {s} (expected 200) — "
                       f"Type4_StateLogicViolation")
        return False
    res = result_of(raw)
    pl = res.get("payload") if isinstance(res, dict) else None
    pl = pl if isinstance(pl, dict) else {}
    if not type_strict_eq(pl, expected):
        DEFECTS.append(f"({tag}) payload order violation: got {pl!r}, "
                       f"expected exactly {expected!r} (last-writer-wins in "
                       f"given order) — Type4_StateLogicViolation "
                       f"(qdrant_state_points_batch_001)")
        return False
    print(f"[{tag}] OK: payload == {expected!r}")
    return True


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spbo2_" + TS + "_"
    C = PFX + "col"
    DIM = 4
    PID = 1

    def vec(x):
        return [float(x), 0.5, 0.75, 1.0]

    try:
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"

        # seed point via the batch endpoint itself (op-key from
        # request_required_paths operations[].upsert.points)
        s = run_batch("seed", C, [
            {"upsert": {"points": [{"id": PID, "vector": vec(1),
                                    "payload": {"seed": 0}}]}}])
        if s != 200:
            print(f"SETUP_ERROR: seed batch status {s}")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        readback("seed", C, PID, {"seed": 0})

        # ---- B1: set + set -> both keys accumulate ----
        s = run_batch("B1", C, [
            {"set_payload": {"payload": {"p1": "a"}, "points": [PID]}},
            {"set_payload": {"payload": {"p2": "b"}, "points": [PID]}},
        ])
        if s != 200:
            print(f"SETUP_ERROR: B1 status {s}")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        readback("B1", C, PID, {"seed": 0, "p1": "a", "p2": "b"})

        # ---- B2: set then overwrite -> ONLY overwrite payload survives ----
        s = run_batch("B2", C, [
            {"set_payload": {"payload": {"p3": "c"}, "points": [PID]}},
            {"overwrite_payload": {"payload": {"only": "z"}, "points": [PID]}},
        ])
        if s != 200:
            print(f"SETUP_ERROR: B2 status {s}")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        readback("B2", C, PID, {"only": "z"})

        # ---- B3: overwrite then set -> BOTH keys survive ----
        s = run_batch("B3", C, [
            {"overwrite_payload": {"payload": {"base": "y"}, "points": [PID]}},
            {"set_payload": {"payload": {"late": "w"}, "points": [PID]}},
        ])
        if s != 200:
            print(f"SETUP_ERROR: B3 status {s}")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        readback("B3", C, PID, {"base": "y", "late": "w"})

        # ---- B4: set then clear_payload -> {} ----
        s = run_batch("B4", C, [
            {"set_payload": {"payload": {"extra": 1}, "points": [PID]}},
            {"clear_payload": {"points": [PID]}},
        ])
        if s != 200:
            print(f"SETUP_ERROR: B4 status {s}")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        readback("B4", C, PID, {})

        # ---- B5: clear then set -> the set payload survives ----
        s = run_batch("B5", C, [
            {"clear_payload": {"points": [PID]}},
            {"set_payload": {"payload": {"after": True}, "points": [PID]}},
        ])
        if s != 200:
            print(f"SETUP_ERROR: B5 status {s}")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        readback("B5", C, PID, {"after": True})

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        if ABORT[0]:
            print("ABORT: environment/transport unavailable mid-run")
            return "SCRIPT_ERROR"
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
