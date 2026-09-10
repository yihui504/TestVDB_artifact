#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_batch_per_op_results_009
# strategy: transaction
# endpoint: points+batch
# constraint_ids: qdrant_behavioral_points_batch_001, qdrant_state_points_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/batch-update
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: the 200 face of qdrant_behavioral_points_batch_001 "batch update
  returns HTTP 200 with ONE RESULT ENTRY PER OPERATION" cross-checked
  against the response_shape grid (result: array; result[].status:
  string; result[].operation_id: integer|null) and the end-state of
  qdrant_state_points_batch_001 ("operations are executed in order"). A
  single 7-op heterogeneous batch exercises 7 of the 8 batchable op
  kinds from the constraint description (upsert, set_payload,
  overwrite_payload, update_vectors, delete_payload, clear_payload,
  delete; delete_vectors' rejection face is covered by
  state_points_batch_reject404_007). After the 200, the FINAL state is
  reconciled op by op: point 901 must carry payload exactly
  {"s":true} ("n" deleted by delete_payload, seed keys untouched later)
  and the updated vector V2; point 902 must be ABSENT (deleted by the
  last op) even though the batch created, overwrote and cleared it
  earlier; exact count must be 1.
  [chunk_points+batch coverage: transaction x
  qdrant_behavioral_points_batch_001 + qdrant_state_points_batch_001
  (7-op heterogeneous batch: per-op result count/shape + end-state
  reconciliation)]
Oracle: batch -> 200 with len(result) == 7, every entry a dict whose
  "status" is a string and whose "operation_id" is an integer or null
  (any other shape = Type4 contract violation); after wait=true:
  GET 901 -> 200 with payload exactly {"s":true} and vector == V2
  (with_vector readback; stale vector or stale "n" key =
  Type4_StateLogicViolation); GET 902 -> 404 (zombie = Type4); exact
  count == 1 (mismatch = Type4); 4xx = setup/contract failure recorded;
  5xx with /healthz alive = Type3_RuntimeFailure; transport failure ->
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

# URLs registered VERBATIM from raw_knowledge api_endpoints[]:
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
        print(f"SETUP_ERROR: {tag} count result.count missing")
        return None
    return cnt


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spbp9_" + TS + "_"
    C = PFX + "col"
    DIM = 4
    V2 = [2.0, 2.5, 3.0, 3.5]

    def vec(x):
        return [float(x), 0.5, 0.75, 1.0]

    try:
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"

        ops = [
            # 1 upsert a second point
            {"upsert": {"points": [
                {"id": 902, "vector": vec(2), "payload": {"m": 2}}]}},
            # 2 set_payload on 901 (seeded below with {"n": 1})
            {"set_payload": {"payload": {"s": True}, "points": [901]}},
            # 3 overwrite_payload on 902 -> payload becomes {"only": 9}
            {"overwrite_payload": {"payload": {"only": 9},
                                   "points": [902]}},
            # 4 update_vectors on 901 -> V2
            {"update_vectors": {"points": [
                {"id": 901, "vector": V2}]}},
            # 5 delete_payload key "n" on 901 -> payload {"s": true}
            {"delete_payload": {"keys": ["n"], "points": [901]}},
            # 6 clear_payload on 902 -> payload {}
            {"clear_payload": {"points": [902]}},
            # 7 delete 902
            {"delete": {"points": [902]}},
        ]

        # seed 901 ({"n": 1}) first so the 7-op chain starts from a known state
        s, raw = safe_request("POST", "batch_update",
                              path_params={"collection_name": C},
                              body={"operations": [
                                  {"upsert": {"points": [
                                      {"id": 901, "vector": vec(1),
                                       "payload": {"n": 1}}]}}]},
                              query_params={"wait": "true"})
        print(f"[seed 901] status={s} raw={str(raw)[:180]}")
        if s != 200:
            print(f"SETUP_ERROR: seed batch status {s}")
            return "SCRIPT_ERROR"

        # ---- the 7-op heterogeneous batch ----
        s, raw = safe_request("POST", "batch_update",
                              path_params={"collection_name": C},
                              body={"operations": ops},
                              query_params={"wait": "true"})
        print(f"[7-op batch] status={s} raw={str(raw)[:400]}")
        if s == 0:
            if not liveness("7op"):
                return "SCRIPT_ERROR"
            DEFECTS.append("(7op) batch transport failure with service "
                           "alive — Type3_RuntimeFailure")
            return "DEFECT_FOUND"
        if 500 <= s <= 599:
            if liveness("7op"):
                DEFECTS.append(f"(7op) batch returned {s} with service "
                               f"alive — Type3_RuntimeFailure — "
                               f"raw={str(raw)[:150]}")
                return "DEFECT_FOUND"
            return "SCRIPT_ERROR"
        if s != 200:
            # the positive contract face (200) is not honored
            DEFECTS.append(f"(7op) heterogeneous all-valid batch returned "
                           f"{s} (contract pins 200 with per-op results) — "
                           f"raw={str(raw)[:200]} — "
                           f"Type4_StateLogicViolation "
                           f"(qdrant_behavioral_points_batch_001)")
        else:
            res = result_of(raw)
            if not isinstance(res, list):
                DEFECTS.append("(7op) 200 batch result is not an array — "
                               "Type4_StateLogicViolation")
            else:
                if len(res) != len(ops):
                    DEFECTS.append(f"(7op) 200 batch returned {len(res)} "
                                   f"result entries for {len(ops)} "
                                   f"operations — one per operation "
                                   f"required — Type4_StateLogicViolation")
                for i, entry in enumerate(res):
                    if not isinstance(entry, dict):
                        DEFECTS.append(f"(7op) result[{i}] is not an "
                                       f"object: {entry!r} — "
                                       f"Type4_StateLogicViolation")
                        continue
                    if not isinstance(entry.get("status"), str):
                        DEFECTS.append(f"(7op) result[{i}].status is not a "
                                       f"string: {entry!r} — "
                                       f"Type4_StateLogicViolation")
                    opid = entry.get("operation_id")
                    if opid is not None and (isinstance(opid, bool)
                                             or not isinstance(opid, int)):
                        DEFECTS.append(f"(7op) result[{i}].operation_id is "
                                       f"neither integer nor null: "
                                       f"{entry!r} — "
                                       f"Type4_StateLogicViolation")
                print(f"[7op] per-op results: {json.dumps(res)[:400]}")

        # ---- end-state reconciliation ----
        s, raw = safe_request("GET", "get_point",
                              path_params={"name": C, "point_id": 901},
                              query_params={"with_payload": "true",
                                            "with_vector": "true"})
        print(f"[get 901] status={s} raw={str(raw)[:300]}")
        if s == 200:
            res = result_of(raw)
            pl = res.get("payload") if isinstance(res, dict) else None
            pl = pl if isinstance(pl, dict) else {}
            vc = res.get("vector") if isinstance(res, dict) else None
            if not type_strict_eq(pl, {"s": True}):
                DEFECTS.append(f"(E1) point 901 payload {pl!r} != "
                               f"{{'s': True}} after the 7-op chain "
                               f"(set_payload + delete_payload order) — "
                               f"Type4_StateLogicViolation")
            if isinstance(vc, list):
                if vc != V2:
                    DEFECTS.append(f"(E1) point 901 vector {vc!r} != "
                                   f"{V2!r} after update_vectors in the "
                                   f"batch — Type4_StateLogicViolation")
            elif isinstance(vc, dict) and "" in vc:
                if vc[""] != V2:
                    DEFECTS.append(f"(E1) point 901 vector {vc['']!r} != "
                                   f"{V2!r} — Type4_StateLogicViolation")
            elif isinstance(vc, dict):
                DEFECTS.append(f"(E1) point 901 vector readback has no "
                               f"default-vector key: {str(vc)[:100]!r} — "
                               f"recorded")
            else:
                DEFECTS.append(f"(E1) point 901 vector readback "
                               f"{str(vc)[:60]!r} is neither list nor "
                               f"object — recorded")
        else:
            DEFECTS.append(f"(E1) GET 901 returned {s} (expected 200) — "
                           f"Type4_StateLogicViolation")

        s, raw = safe_request("GET", "get_point",
                              path_params={"name": C, "point_id": 902})
        print(f"[get 902] status={s} raw={str(raw)[:160]}")
        if s == 200:
            DEFECTS.append("(E2) point 902 still retrievable after the "
                           "batch's trailing delete op — zombie point — "
                           "Type4_StateLogicViolation")
        elif s != 404 and s != 0 and not (500 <= s <= 599):
            DEFECTS.append(f"(E2) GET 902 returned {s} (expected 404) — "
                           f"Type4_StateLogicViolation")

        cnt = exact_count("E3", C)
        if cnt is not None and cnt != 1:
            DEFECTS.append(f"(E3) exact count {cnt} != 1 after the 7-op "
                           f"batch (only 901 must survive) — "
                           f"Type4_StateLogicViolation")

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
