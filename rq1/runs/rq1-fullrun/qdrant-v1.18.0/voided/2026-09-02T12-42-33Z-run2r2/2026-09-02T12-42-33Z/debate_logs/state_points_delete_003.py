#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_delete_003
# strategy: delete_consistency
# endpoint: points+delete
# constraint_ids: qdrant_bc_delete_points_invisibility_001
# source_url: https://qdrant.tech/documentation/manage-data/points/
# doc_version: unknown
"""
Attack: post-DELETE invisibility on every read face (Strategy 2 multi-face)
  x qdrant_bc_delete_points_invisibility_001 "points deleted by id or
  filter (wait=true) are no longer returned by reads" (state invariant
  qdrant_inv_point_delete_gone_001 backs it). Scenario follows the
  contract verbatim: upsert 10 points (grp=a ids 0-4, grp=b ids 5-9) ->
  (F1) delete by ids [1,3] with wait=true -> (F2) delete by filter
  grp=b with wait=true. After EACH delete, five read faces are probed:
  batch-get (POST /collections/{collection_name}/points, result is an
  array), single get (GET /points/{id} -> 404 for deleted), filtered
  scroll (result.points array), filtered query (result.points array,
  universal API) and legacy search (result is an array). Shape oracles
  cross-checked against the contract response_shape: query/scroll use
  result.points; search/batch-get use the result array directly. Deleted
  ids must be absent from every face (zombie = Type4) while survivors
  must remain visible on every face (over-deletion = Type4); count is
  arithmetic-derived: 10 - 2 (F1) - 5 (F2) = 3.
  [chunk_points+delete coverage: delete_consistency x
  qdrant_bc_delete_points_invisibility_001 (ids-delete + filter-delete x
  batch-get / single-get / scroll / query / search faces)]
Oracle: F1 -> after ids-delete 200: batch-get of ids 0..9 returns exactly
  {0,2,4,5,6,7,8,9}; GET id 1 -> 404 and GET id 2 -> 200; filtered
  scroll/query/search on grp=a return ids that are subsets of {0,2,4} and
  include all of {0,2,4}; F2 -> after filter-delete 200: batch-get of
  5..9 returns [], GET id 7 -> 404, unfiltered scroll returns exactly
  {0,2,4}, filtered query/search on grp=b return empty result lists, and
  exact count == 3; any deleted id visible on any face =
  Type4_StateLogicViolation (zombie), any survivor missing =
  Type4_StateLogicViolation (over-deletion); 5xx with /healthz alive =
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

# URLs used VERBATIM from raw_knowledge api_endpoints[]:
#   {"endpoint_name": "Delete Points", "method": "POST",
#    "url": "/collections/{collection_name}/points/delete"}     -> runtime delete_points
#   {"endpoint_name": "Retrieve Points (batch get)", "method": "POST",
#    "url": "/collections/{collection_name}/points"}            -> get_points_by_ids
# runtime PATHS already carries delete_points/get_point/scroll/query/search/count
# verbatim; only the POST batch-get face needs registration.
rt.PATHS["get_points_by_ids"] = "/collections/{collection_name}/points"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if k in ('get_points_by_ids', 'delete_points')]}")

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


def transport_or_5xx(tag, s, raw):
    """True when s is 0/5xx (handled with mandatory liveness re-check)."""
    if s == 0:
        if not liveness(tag):
            ABORT[0] = True
        return True
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) returned {s} with service alive — "
                           f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
        else:
            ABORT[0] = True
        return True
    return False


def ids_from_result_array(tag, raw):
    """batch-get / search faces: result IS the array (response_shape result[])."""
    res = result_of(raw)
    if not isinstance(res, list):
        print(f"SETUP_ERROR: {tag} result is not an array — raw={str(raw)[:200]}")
        return None
    return [p.get("id") for p in res if isinstance(p, dict)]


def ids_from_result_points(tag, raw):
    """scroll / query faces: envelope result.points (response_shape)."""
    res = result_of(raw)
    pts = res.get("points") if isinstance(res, dict) else None
    if not isinstance(pts, list):
        print(f"SETUP_ERROR: {tag} result.points missing — raw={str(raw)[:200]}")
        return None
    return [p.get("id") for p in pts if isinstance(p, dict)]


def face_batch_get(tag, coll, ids):
    s, raw = safe_request("POST", "get_points_by_ids",
                          path_params={"collection_name": coll},
                          body={"ids": ids})
    print(f"[{tag} batch-get {len(ids)} ids] status={s} raw={str(raw)[:200]}")
    if transport_or_5xx(tag, s, raw):
        return None
    if s != 200:
        print(f"SETUP_ERROR: {tag} batch-get returned {s}")
        return None
    return ids_from_result_array(tag, raw)


def face_single_get(coll, pid):
    s, raw = safe_request("GET", "get_point",
                          path_params={"name": coll, "point_id": pid},
                          query_params={"with_payload": "false"})
    print(f"[get {pid}] status={s} raw={str(raw)[:140]}")
    if transport_or_5xx(f"get {pid}", s, raw):
        return None
    return s


def face_scroll(tag, coll, flt=None):
    body = {"limit": 20, "with_payload": False}
    if flt is not None:
        body["filter"] = flt
    s, raw = safe_request("POST", "scroll", path_params={"name": coll},
                          body=body)
    print(f"[{tag} scroll flt={json.dumps(flt)[:80]}] status={s} "
          f"raw={str(raw)[:200]}")
    if transport_or_5xx(tag, s, raw):
        return None
    if s != 200:
        print(f"SETUP_ERROR: {tag} scroll returned {s}")
        return None
    return ids_from_result_points(tag, raw)


def face_query(tag, coll, flt, vec):
    s, raw = safe_request("POST", "query", path_params={"name": coll},
                          body={"query": {"nearest": vec},
                                "filter": flt, "limit": 20})
    print(f"[{tag} query flt={json.dumps(flt)[:80]}] status={s} "
          f"raw={str(raw)[:200]}")
    if transport_or_5xx(tag, s, raw):
        return None
    if s != 200:
        print(f"SETUP_ERROR: {tag} query returned {s}")
        return None
    return ids_from_result_points(tag, raw)


def face_search(tag, coll, flt, vec):
    s, raw = safe_request("POST", "search", path_params={"name": coll},
                          body={"vector": vec, "filter": flt, "limit": 20})
    print(f"[{tag} search flt={json.dumps(flt)[:80]}] status={s} "
          f"raw={str(raw)[:200]}")
    if transport_or_5xx(tag, s, raw):
        return None
    if s != 200:
        print(f"SETUP_ERROR: {tag} search returned {s}")
        return None
    return ids_from_result_array(tag, raw)


def exact_count(tag, coll):
    s, raw = safe_request("POST", "count", path_params={"name": coll},
                          body={"exact": True})
    print(f"[{tag} count] status={s} raw={str(raw)[:160]}")
    if transport_or_5xx(tag, s, raw):
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


def check_face(tag, got, forbidden, required):
    """got=None means transport/setup failure (already handled)."""
    if got is None:
        return
    leaked = sorted(set(got) & set(forbidden))
    if leaked:
        DEFECTS.append(f"({tag}) deleted ids {leaked} still visible — "
                       f"zombie — Type4_StateLogicViolation")
    missing = sorted(set(required) - set(got))
    if missing:
        DEFECTS.append(f"({tag}) survivor ids {missing} missing from face — "
                       f"over-deletion — Type4_StateLogicViolation")


def delete_ids(tag, coll, ids):
    s, raw = safe_request("POST", "delete_points",
                          path_params={"name": coll},
                          body={"points": ids},
                          query_params={"wait": "true"})
    print(f"[{tag} delete ids {ids}] status={s} raw={str(raw)[:160]}")
    if transport_or_5xx(tag, s, raw):
        return False
    return s == 200


def delete_filter(tag, coll, flt):
    s, raw = safe_request("POST", "delete_points",
                          path_params={"name": coll},
                          body={"filter": flt},
                          query_params={"wait": "true"})
    print(f"[{tag} delete filter {json.dumps(flt)[:100]}] status={s} "
          f"raw={str(raw)[:160]}")
    if transport_or_5xx(tag, s, raw):
        return False
    return s == 200


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spdel3_" + TS + "_"
    C = PFX + "col"
    DIM = 4
    NEAR = [0.1, 0.5, 0.75, 1.0]

    def vec(i):
        return [0.1 + 0.01 * (i % 10), 0.5, 0.75, 1.0]

    def grp_of(i):
        return "a" if i < 5 else "b"

    flt_grp = lambda g: {"must": [{"key": "grp", "match": {"value": g}}]}

    try:
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        s, raw = safe_request("PUT", "upsert_points",
                              path_params={"name": C},
                              body={"points": [
                                  {"id": i, "vector": vec(i),
                                   "payload": {"grp": grp_of(i), "n": i}}
                                  for i in range(10)]},
                              query_params={"wait": "true"})
        print(f"[seed upsert 10 pts] status={s} raw={str(raw)[:160]}")
        if s != 200:
            print("SETUP_ERROR: seed upsert failed")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if exact_count("seed", C) != 10:
            print("SETUP_ERROR: seed count != 10")
            return "SCRIPT_ERROR"

        # ---- F1: delete by ids [1, 3] (wait=true) -> 5 faces ----
        if not delete_ids("F1", C, [1, 3]):
            print("SETUP_ERROR: F1 ids-delete not 200")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        got = face_batch_get("F1-batch-get", C, list(range(10)))
        check_face("F1-batch-get", got, forbidden=[1, 3],
                   required=[0, 2, 4, 5, 6, 7, 8, 9])
        for pid, expect in ((1, 404), (2, 200)):
            st = face_single_get(C, pid)
            if st is not None and st != expect:
                DEFECTS.append(f"(F1-single-get) id {pid} returned {st} "
                               f"(expected {expect}) — "
                               f"{'zombie' if expect == 404 else 'over-deletion'} "
                               f"— Type4_StateLogicViolation")
        got = face_scroll("F1-scroll-a", C, flt_grp("a"))
        check_face("F1-scroll-a", got, forbidden=[1, 3], required=[0, 2, 4])
        got = face_query("F1-query-a", C, flt_grp("a"), NEAR)
        check_face("F1-query-a", got, forbidden=[1, 3], required=[0, 2, 4])
        got = face_search("F1-search-a", C, flt_grp("a"), NEAR)
        check_face("F1-search-a", got, forbidden=[1, 3], required=[0, 2, 4])
        cnt = exact_count("F1", C)
        if cnt is not None and cnt != 8:
            DEFECTS.append(f"(F1) exact count {cnt} != 10-2=8 — "
                           f"Type4_StateLogicViolation")

        # ---- F2: delete by filter grp=b (wait=true) -> 5 faces ----
        if not delete_filter("F2", C, flt_grp("b")):
            print("SETUP_ERROR: F2 filter-delete not 200")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        got = face_batch_get("F2-batch-get-b", C, [5, 6, 7, 8, 9])
        check_face("F2-batch-get-b", got, forbidden=[5, 6, 7, 8, 9], required=[])
        got = face_batch_get("F2-batch-get-survivors", C, [0, 2, 4])
        check_face("F2-batch-get-survivors", got, forbidden=[],
                   required=[0, 2, 4])
        st = face_single_get(C, 7)
        if st is not None and st != 404:
            DEFECTS.append(f"(F2-single-get) deleted id 7 returned {st} "
                           f"(expected 404) — zombie — "
                           f"Type4_StateLogicViolation")
        got = face_scroll("F2-scroll-all", C, None)
        check_face("F2-scroll-all", got, forbidden=[5, 6, 7, 8, 9],
                   required=[0, 2, 4])
        got = face_query("F2-query-b", C, flt_grp("b"), NEAR)
        if got is not None and got:
            DEFECTS.append(f"(F2-query-b) filtered query returned ids "
                           f"{sorted(set(got))} after grp=b filter-delete — "
                           f"zombie — Type4_StateLogicViolation")
        got = face_search("F2-search-b", C, flt_grp("b"), NEAR)
        if got is not None and got:
            DEFECTS.append(f"(F2-search-b) filtered search returned ids "
                           f"{sorted(set(got))} after grp=b filter-delete — "
                           f"zombie — Type4_StateLogicViolation")
        cnt = exact_count("F2", C)
        if cnt is not None and cnt != 3:
            DEFECTS.append(f"(F2) exact count {cnt} != 10-2-5=3 — "
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
