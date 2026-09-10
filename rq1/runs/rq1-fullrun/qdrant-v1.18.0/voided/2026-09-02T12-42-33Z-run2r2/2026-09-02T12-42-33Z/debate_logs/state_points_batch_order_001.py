#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_batch_order_001
# strategy: transaction
# endpoint: points+batch
# constraint_ids: qdrant_state_points_batch_001
# source_url: https://qdrant.tech/documentation/manage-data/points/
# doc_version: current (site latest; no version archive)
"""
Attack: sequence-order semantics (transaction strategy, order face) x
  qdrant_state_points_batch_001 "batch operations are applied sequentially
  in the order given; each operation reports its own result". The same two
  opposing ops (upsert id P / delete id P) are submitted in BOTH orders as
  separate single-batch requests; sequential semantics REQUIRE opposite
  final states: [upsert, delete] -> P absent; [delete, upsert] -> P present
  with the upserted payload (the leading no-op delete must not block the
  later upsert). Identical outcomes from both orders = order not honored.
  Third face (G9 consistent disposition): the DOC-worded op key
  "delete_points" (constraint description) vs the OpenAPI key "delete"
  (request_required_paths operations[].delete) must delete identically when
  accepted. Every 200 batch must carry one result entry per operation
  (response_shape: result array, result[].status string).
  [chunk_points+batch coverage: transaction/order x
  qdrant_state_points_batch_001 (upsert+delete both orders + op-key
  disposition + per-op result count)]
Oracle: batch [upsert P, delete P] wait=true -> 200 and GET P -> 404 with
  exact count 0; batch [delete P, upsert P payload p2] wait=true -> 200 and
  GET P -> 200 with payload exactly {"phase":"p2"} and count 1; the SAME
  outcome from both orders (P absent in both, or p1-payload in both) =
  Type4_StateLogicViolation (order violation, qdrant_state_points_batch_001);
  "delete_points"-key batch: if 200 -> P absent (200 with P surviving =
  Type4), if 4xx -> recorded as consistent rejection (no defect); 200
  batch with len(result) != len(operations) = Type4 per-op-results
  violation; any 5xx with /healthz alive = Type3_RuntimeFailure; transport
  failure -> liveness re-check before any verdict.
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

# points+batch is not in the runtime PATHS whitelist — register VERBATIM
# from raw_knowledge api_endpoints[]:
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
    """POST points+batch with wait=true. Returns (status, result_list_or_None)."""
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
        return s, None
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) batch returned {s} with service alive "
                           f"— Type3_RuntimeFailure — raw={str(raw)[:150]}")
        else:
            ABORT[0] = True
        return s, None
    res = None
    if s == 200:
        res = result_of(raw)
        if not isinstance(res, list):
            DEFECTS.append(f"({tag}) 200 batch result is not an array — "
                           f"raw={str(raw)[:200]} — Type4_StateLogicViolation")
            res = None
        elif len(res) != len(ops):
            DEFECTS.append(f"({tag}) 200 batch returned {len(res)} result "
                           f"entries for {len(ops)} operations (one per "
                           f"operation required) — Type4_StateLogicViolation")
        else:
            for i, entry in enumerate(res):
                if not isinstance(entry, dict) or not isinstance(
                        entry.get("status"), str):
                    DEFECTS.append(
                        f"({tag}) per-op result[{i}] missing string status "
                        f"— entry={entry!r} — Type4_StateLogicViolation")
    return s, res


def get_payload(coll, pid):
    """GET single point with payload; returns (status, payload_dict_or_None)."""
    s, raw = safe_request("GET", "get_point",
                          path_params={"name": coll, "point_id": pid},
                          query_params={"with_payload": "true"})
    print(f"[get {pid}] status={s} raw={str(raw)[:180]}")
    if s != 200:
        return s, None
    res = result_of(raw)
    pl = res.get("payload") if isinstance(res, dict) else None
    return s, (pl if isinstance(pl, dict) else {})


def exact_count(tag, coll):
    s, raw = safe_request("POST", "count", path_params={"name": coll},
                          body={"exact": True})
    print(f"[{tag} count] status={s} raw={str(raw)[:160]}")
    if s == 0 or 500 <= s <= 599:
        if s == 0 and not liveness(tag):
            ABORT[0] = True
            return None
        if 500 <= s <= 599 and liveness(tag):
            DEFECTS.append(f"({tag}) count returned {s} with service alive "
                           f"— Type3_RuntimeFailure")
            return None
        ABORT[0] = True
        return None
    if s != 200:
        print(f"SETUP_ERROR: {tag} count returned {s}")
        return None
    res = result_of(raw)
    cnt = res.get("count") if isinstance(res, dict) else None
    if isinstance(cnt, bool) or not isinstance(cnt, int):
        print(f"SETUP_ERROR: {tag} count result.count missing — raw={str(raw)[:200]}")
        return None
    return cnt


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spbo1_" + TS + "_"
    C = PFX + "col"
    DIM = 4
    P = 501

    def vec(x):
        return [float(x), 0.5, 0.75, 1.0]

    try:
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"

        # ---- Phase 1: [upsert P, delete P] -> P must be ABSENT ----
        s1, _ = run_batch("P1-upsert-then-delete", C, [
            {"upsert": {"points": [{"id": P, "vector": vec(1),
                                    "payload": {"phase": "p1"}}]}},
            {"delete": {"points": [P]}},
        ])
        if s1 != 200:
            print(f"SETUP_ERROR: P1 batch status {s1}")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        st, pl = get_payload(C, P)
        if st == 200:
            DEFECTS.append(f"(P1) after [upsert,delete] order GET {P} "
                           f"returned 200 payload={pl!r} — point must be "
                           f"absent — Type4_StateLogicViolation")
        elif st != 404:
            if st == 0:
                liveness("P1 get")
            elif 500 <= st <= 599 and liveness("P1 get"):
                DEFECTS.append(f"(P1) GET after [upsert,delete] returned "
                               f"{st} with service alive — Type3_RuntimeFailure")
            else:
                DEFECTS.append(f"(P1) GET after [upsert,delete] returned "
                               f"{st} (expected 404) — Type4_StateLogicViolation")
        else:
            print("[P1] OK: [upsert,delete] -> point absent")
        got = exact_count("P1", C)
        if got is not None and got != 0:
            DEFECTS.append(f"(P1 count) exact count {got} != 0 after "
                           f"[upsert,delete] — Type4_StateLogicViolation")

        # ---- Phase 2: [delete P, upsert P payload p2] -> P must be PRESENT ----
        s2, _ = run_batch("P2-delete-then-upsert", C, [
            {"delete": {"points": [P]}},
            {"upsert": {"points": [{"id": P, "vector": vec(2),
                                    "payload": {"phase": "p2"}}]}},
        ])
        if s2 != 200:
            print(f"SETUP_ERROR: P2 batch status {s2}")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        st, pl = get_payload(C, P)
        if st != 200:
            DEFECTS.append(f"(P2) after [delete,upsert] order GET {P} "
                           f"returned {st} (expected 200) — the leading "
                           f"no-op delete must not suppress the later "
                           f"upsert — Type4_StateLogicViolation")
        elif not type_strict_eq(pl, {"phase": "p2"}):
            DEFECTS.append(f"(P2) after [delete,upsert] payload {pl!r} != "
                           f"{{'phase': 'p2'}} — Type4_StateLogicViolation")
        else:
            print("[P2] OK: [delete,upsert] -> point present with p2 payload")
        got = exact_count("P2", C)
        if got is not None and got != 1:
            DEFECTS.append(f"(P2 count) exact count {got} != 1 after "
                           f"[delete,upsert] — Type4_StateLogicViolation")

        # order-violation cross-check: identical outcomes from both orders
        if s1 == 200 and s2 == 200 and st == 404:
            DEFECTS.append("(order) [upsert,delete] and [delete,upsert] "
                           "produced the SAME outcome (absent) — sequential "
                           "order not honored — Type4_StateLogicViolation "
                           "(qdrant_state_points_batch_001)")

        # ---- Phase 3: DOC-worded key "delete_points" disposition ----
        s3, _ = run_batch("P3-delete-points-key", C, [
            {"upsert": {"points": [{"id": 502, "vector": vec(3),
                                    "payload": {"k": "v"}}]}},
            {"delete_points": {"points": [502]}},
        ])
        if s3 == 200:
            st, pl = get_payload(C, 502)
            if st != 404:
                DEFECTS.append(f"(P3) 'delete_points'-key batch returned 200 "
                               f"but point 502 still retrievable ({st}) — "
                               f"Type4_StateLogicViolation")
            else:
                print("[P3] OK: 'delete_points' key deleted like 'delete'")
        elif 400 <= s3 <= 499:
            st, pl = get_payload(C, 502)
            if st == 200:
                print("[P3] consistent rejection: 'delete_points' key "
                      f"rejected with {s3} and its upsert not applied — "
                      "recorded, no defect")
            else:
                DEFECTS.append(f"(P3) 'delete_points'-key batch rejected "
                               f"with {s3} yet earlier upsert of 502 not "
                               f"durable (GET {st}) — rejected batch must "
                               f"not half-apply — Type4_StateLogicViolation")
        # 5xx / transport already handled inside run_batch

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
