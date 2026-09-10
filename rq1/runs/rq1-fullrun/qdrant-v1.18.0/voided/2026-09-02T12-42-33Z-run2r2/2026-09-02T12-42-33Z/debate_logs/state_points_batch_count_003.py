#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_batch_count_003
# strategy: count_consistency
# endpoint: points+batch
# constraint_ids: qdrant_state_points_batch_001, qdrant_behavioral_points_batch_001
# source_url: https://qdrant.tech/documentation/manage-data/points/
# doc_version: current (site latest; no version archive)
"""
Attack: CRUD-then-COUNT consistency (Strategy 1) executed inside ONE batch
  request x qdrant_state_points_batch_001 "operations are executed in order
  inside one batch request" + qdrant_behavioral_points_batch_001 "returns
  200 with per-operation results". M1 is a deliberately NET-ZERO mixed
  batch (upsert 3 new + delete 2 old + re-upsert 1 existing + delete 1 of
  the new): the exact count must remain unchanged AND every touched id
  must read back its order-correct state (present set {3,10,12}, absent
  set {1,2,11}, id 3 carrying the SECOND write's payload). M2 adds a
  duplicate-id upsert inside a single op ({20 v1},{20 v2} in one points
  list) plus a delete: count math must be +1-1=0 relative net, and the
  duplicate id must hold the LAST list entry's payload. Persistence is
  judged via point readback (batch get + exact count), not the response
  alone.
  [chunk_points+batch coverage: count_consistency x
  qdrant_state_points_batch_001 + qdrant_behavioral_points_batch_001
  (net-zero mixed batch + duplicate-id-in-op + per-op result entries)]
Oracle: M1 200 -> exact count == 3 (before == after), batch-get returns
  exactly ids {3,10,12} with id 3 payload == {"gen":2}, ids {1,2,11}
  absent; M2 200 -> exact count == 2 with visible set {3,10,20} and id 20
  payload == {"try":2}; any count/visibility/payload mismatch =
  Type4_StateLogicViolation; 200 batch with len(result) !=
  len(operations) = Type4 per-op-results violation; 5xx with /healthz
  alive = Type3_RuntimeFailure; transport failure -> liveness re-check
  before any verdict.
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
#   {"path": "points+get", "method": "POST",
#    "url": "/collections/{collection_name}/points"}
rt.PATHS["batch_update"] = "/collections/{collection_name}/points/batch"
rt.PATHS["get_points_by_ids"] = "/collections/{collection_name}/points"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if k in ('batch_update', 'get_points_by_ids')]}")

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
                           f"Type4_StateLogicViolation "
                           f"(qdrant_behavioral_points_batch_001)")
    return s


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


def visible_points(tag, coll, ids):
    """Batch-get by ids; returns {id: payload} for the ids present."""
    s, raw = safe_request("POST", "get_points_by_ids",
                          path_params={"collection_name": coll},
                          body={"ids": ids, "with_payload": True})
    print(f"[{tag} get {len(ids)} ids] status={s} raw={str(raw)[:260]}")
    if s == 0:
        if not liveness(tag):
            ABORT[0] = True
        return None
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) batch-get returned {s} with service "
                           f"alive — Type3_RuntimeFailure")
        else:
            ABORT[0] = True
        return None
    if s != 200:
        print(f"SETUP_ERROR: {tag} batch-get returned {s}")
        return None
    res = result_of(raw)
    if not isinstance(res, list):
        print(f"SETUP_ERROR: {tag} batch-get result not a list — raw={str(raw)[:200]}")
        return None
    out = {}
    for p in res:
        if isinstance(p, dict) and "id" in p:
            out[p["id"]] = p.get("payload") if isinstance(p.get("payload"), dict) else {}
    return out


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spbc3_" + TS + "_"
    C = PFX + "col"
    DIM = 4

    def vec(x):
        return [float(x), 0.5, 0.75, 1.0]

    try:
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"

        # seed 3 points via one batch (ids 1,2,3)
        s = run_batch("seed", C, [{"upsert": {"points": [
            {"id": i, "vector": vec(i), "payload": {"n": i}} for i in (1, 2, 3)]}}])
        if s != 200:
            print(f"SETUP_ERROR: seed batch status {s}")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        before = exact_count("seed", C)
        if before != 3:
            print(f"SETUP_ERROR: seed count {before} != 3")
            return "SCRIPT_ERROR"

        # ---- M1: net-zero mixed batch ----
        # +3 (10,11,12) -2 (1,2) +0 (re-upsert 3 with gen:2) -1 (11) => count 3
        s = run_batch("M1", C, [
            {"upsert": {"points": [
                {"id": j, "vector": vec(j), "payload": {"n": j}}
                for j in (10, 11, 12)]}},
            {"delete": {"points": [1, 2]}},
            {"upsert": {"points": [
                {"id": 3, "vector": vec(3), "payload": {"gen": 2}}]}},
            {"delete": {"points": [11]}},
        ])
        if s != 200:
            print(f"SETUP_ERROR: M1 status {s}")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        after = exact_count("M1", C)
        if after is not None and after != 3:
            DEFECTS.append(f"(M1) net-zero mixed batch: exact count "
                           f"{after} != 3 (before {before}) — "
                           f"Type4_StateLogicViolation")
        vis = visible_points("M1", C, [1, 2, 3, 10, 11, 12])
        if vis is not None:
            got_ids = set(vis.keys())
            want_ids = {3, 10, 12}
            if got_ids != want_ids:
                DEFECTS.append(f"(M1) visible set {sorted(got_ids)} != "
                               f"{sorted(want_ids)} — Type4_StateLogicViolation")
            if 3 in vis and not type_strict_eq(vis[3], {"gen": 2}):
                DEFECTS.append(f"(M1) re-upserted id 3 payload {vis[3]!r} "
                               f"!= {{'gen': 2}} (last write in order must "
                               f"win) — Type4_StateLogicViolation")

        # ---- M2: duplicate id inside ONE upsert op + delete ----
        # upsert {20 try:1},{20 try:2} in one points list -> +1 (try:2 wins)
        # delete 12 -> -1  => count 2, visible {3,10,20}
        s = run_batch("M2", C, [
            {"upsert": {"points": [
                {"id": 20, "vector": vec(20), "payload": {"try": 1}},
                {"id": 20, "vector": vec(21), "payload": {"try": 2}}]}},
            {"delete": {"points": [12]}},
        ])
        if s != 200:
            print(f"SETUP_ERROR: M2 status {s}")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        cnt = exact_count("M2", C)
        if cnt is not None and cnt != 2:
            DEFECTS.append(f"(M2) duplicate-id upsert + delete: exact count "
                           f"{cnt} != 2 — Type4_StateLogicViolation")
        vis = visible_points("M2", C, [3, 10, 12, 20])
        if vis is not None:
            got_ids = set(vis.keys())
            want_ids = {3, 10, 20}
            if got_ids != want_ids:
                DEFECTS.append(f"(M2) visible set {sorted(got_ids)} != "
                               f"{sorted(want_ids)} — Type4_StateLogicViolation")
            if 20 in vis and not type_strict_eq(vis[20], {"try": 2}):
                DEFECTS.append(f"(M2) duplicate id 20 payload {vis[20]!r} "
                               f"!= {{'try': 2}} (last list entry must "
                               f"win) — Type4_StateLogicViolation")

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
