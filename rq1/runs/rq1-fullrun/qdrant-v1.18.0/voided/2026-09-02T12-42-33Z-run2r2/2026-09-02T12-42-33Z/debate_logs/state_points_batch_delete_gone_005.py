#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_batch_delete_gone_005
# strategy: delete_consistency
# endpoint: points+batch
# constraint_ids: qdrant_state_points_batch_001
# source_url: https://qdrant.tech/documentation/manage-data/points/
# doc_version: current (site latest; no version archive)
"""
Attack: post-DELETE consistency (Strategy 2) with the delete carried INSIDE
  a batch x qdrant_state_points_batch_001 "batch operations are applied
  sequentially in the order given". (D1) a single-batch delete of all 6
  seeded points must leave the collection empty on EVERY read face: exact
  count 0, single GET of deleted ids 404, scroll returning an empty point
  list; (D2) resurrection through the same batch endpoint (upsert of a
  previously deleted id) must return the point with exactly the new
  payload and bump the count to 1 (a deleted id's address stays reusable);
  (D3) the filter-form delete branch (request_required_paths
  operations[].delete.filter) must remove the resurrected id via
  has_id filter and return the collection to 0. Persistence is judged via
  point readback, not the response alone.
  [chunk_points+batch coverage: delete_consistency x
  qdrant_state_points_batch_001 (batch delete-all + multi-face absence +
  batch resurrection + filter-form delete)]
Oracle: D1 batch delete -> 200 then exact count == 0, GET ids 2 and 5 ->
  404 (200 = zombie Type4), scroll result.points == [] (leaked ids =
  Type4); D2 batch re-upsert -> GET 200 with payload exactly
  {"reborn":true} and count == 1; D3 filter-delete -> GET 404 and count
  == 0 (survivor = Type4); 200 batch with len(result) != len(operations)
  = Type4 per-op-results violation; 5xx with /healthz alive =
  Type3_RuntimeFailure; transport failure -> liveness re-check before any
  verdict.
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


def get_payload(coll, pid):
    s, raw = safe_request("GET", "get_point",
                          path_params={"name": coll, "point_id": pid},
                          query_params={"with_payload": "true"})
    print(f"[get {pid}] status={s} raw={str(raw)[:200]}")
    if s != 200:
        return s, None
    res = result_of(raw)
    pl = res.get("payload") if isinstance(res, dict) else None
    return s, (pl if isinstance(pl, dict) else {})


def scroll_ids(tag, coll):
    s, raw = safe_request("POST", "scroll", path_params={"name": coll},
                          body={"limit": 10, "with_payload": False})
    print(f"[{tag} scroll] status={s} raw={str(raw)[:220]}")
    if s == 0:
        if not liveness(tag):
            ABORT[0] = True
        return None
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) scroll returned {s} with service "
                           f"alive — Type3_RuntimeFailure")
        else:
            ABORT[0] = True
        return None
    if s != 200:
        print(f"SETUP_ERROR: {tag} scroll returned {s}")
        return None
    res = result_of(raw)
    pts = res.get("points") if isinstance(res, dict) else None
    if not isinstance(pts, list):
        print(f"SETUP_ERROR: {tag} scroll result.points missing")
        return None
    return [p.get("id") for p in pts if isinstance(p, dict)]


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spbd5_" + TS + "_"
    C = PFX + "col"
    DIM = 4

    def vec(x):
        return [float(x), 0.5, 0.75, 1.0]

    def payload_of(i):
        return {"n": i, "parity": "odd" if i % 2 else "even"}

    try:
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"

        # seed 6 points via one batch
        s = run_batch("seed", C, [{"upsert": {"points": [
            {"id": i, "vector": vec(i), "payload": payload_of(i)}
            for i in range(6)]}}])
        if s != 200:
            print(f"SETUP_ERROR: seed batch status {s}")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if exact_count("seed", C) != 6:
            print("SETUP_ERROR: seed count != 6")
            return "SCRIPT_ERROR"

        # ---- D1: batch delete-all, multi-face absence ----
        s = run_batch("D1-delete-all", C, [
            {"delete": {"points": list(range(6))}}])
        if s != 200:
            print(f"SETUP_ERROR: D1 status {s}")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        cnt = exact_count("D1", C)
        if cnt is not None and cnt != 0:
            DEFECTS.append(f"(D1) exact count {cnt} != 0 after batch "
                           f"delete-all — Type4_StateLogicViolation")
        for pid in (2, 5):
            st, pl = get_payload(C, pid)
            if st == 200:
                DEFECTS.append(f"(D1) deleted id {pid} still retrievable "
                               f"(200, payload={pl!r}) — zombie point — "
                               f"Type4_StateLogicViolation")
            elif st == 0:
                liveness(f"D1 get {pid}")
            elif 500 <= st <= 599:
                if liveness(f"D1 get {pid}"):
                    DEFECTS.append(f"(D1) GET deleted {pid} returned {st} "
                                   f"with service alive — "
                                   f"Type3_RuntimeFailure")
            elif st != 404:
                DEFECTS.append(f"(D1) GET deleted {pid} returned {st} "
                               f"(expected 404) — Type4_StateLogicViolation")
        leaked = scroll_ids("D1", C)
        if leaked is not None and leaked:
            DEFECTS.append(f"(D1) scroll after delete-all leaked ids "
                           f"{leaked} — Type4_StateLogicViolation")

        # ---- D2: resurrection through the batch endpoint ----
        s = run_batch("D2-resurrect", C, [
            {"upsert": {"points": [
                {"id": 2, "vector": vec(2), "payload": {"reborn": True}}]}}])
        if s != 200:
            print(f"SETUP_ERROR: D2 status {s}")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        st, pl = get_payload(C, 2)
        if st != 200:
            DEFECTS.append(f"(D2) resurrected id 2 GET returned {st} "
                           f"(expected 200) — Type4_StateLogicViolation")
        elif not type_strict_eq(pl, {"reborn": True}):
            DEFECTS.append(f"(D2) resurrected id 2 payload {pl!r} != "
                           f"{{'reborn': True}} — "
                           f"Type4_StateLogicViolation")
        else:
            print("[D2] OK: resurrected id 2 with exact new payload")
        cnt = exact_count("D2", C)
        if cnt is not None and cnt != 1:
            DEFECTS.append(f"(D2) exact count {cnt} != 1 after "
                           f"resurrecting one id — "
                           f"Type4_StateLogicViolation")

        # ---- D3: filter-form delete inside a batch ----
        s = run_batch("D3-filter-delete", C, [
            {"delete": {"filter": {"must": [{"has_id": [2]}]}}}])
        if s != 200:
            print(f"SETUP_ERROR: D3 status {s}")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        st, pl = get_payload(C, 2)
        if st != 404:
            DEFECTS.append(f"(D3) filter-form delete left id 2 "
                           f"retrievable ({st}) — Type4_StateLogicViolation")
        cnt = exact_count("D3", C)
        if cnt is not None and cnt != 0:
            DEFECTS.append(f"(D3) exact count {cnt} != 0 after "
                           f"filter-delete — Type4_StateLogicViolation")

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
