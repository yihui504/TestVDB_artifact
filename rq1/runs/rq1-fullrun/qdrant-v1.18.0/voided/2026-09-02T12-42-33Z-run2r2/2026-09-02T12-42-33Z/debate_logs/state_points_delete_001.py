#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_delete_001
# strategy: delete_consistency
# endpoint: points+delete
# constraint_ids: qdrant_state_points_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/delete-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: delete-idempotence + filter-delete completeness (Strategies 2-3)
  x qdrant_state_points_delete_001 "delete of non-existent point ids returns
  success (idempotent); filter-based delete removes every matching point
  (all points when the filter matches all)". (P1) deleting never-upserted
  ids [9001,9002] twice must return 200 BOTH times (idempotent success per
  the constraint; threat-model by-design confirms 200 is the CORRECT
  disposition for idempotent point DELETE) and must not change the exact
  count. (D2) filter-delete on key grp == "a" must remove EXACTLY the 4
  matching points: count arithmetic 8-4=4, batch-get of ids 0..7 returns
  exactly {4,5,6,7} (a deleted id reappearing = zombie; a survivor
  vanishing = over-deletion). (D3a) a structurally matches-all filter
  (must key grp match any [a,b]) must wipe every point: count 0, batch-get
  of all seeded ids []. (D3b) the EMPTY filter selector {"filter": {}}
  must also match everything per the constraint's "filter is empty/matches
  everything" clause: after reseeding 3 points it must return 200 and
  leave count 0. All count expectations are arithmetic-derived from the
  seeded id sets (no id collisions: every id is created exactly once by
  this script's own prefix collection).
  [chunk_points+delete coverage: delete_consistency x
  qdrant_state_points_delete_001 (idempotent non-existent delete x2 +
  partial filter-delete arithmetic + matches-all filter wipe + empty-filter
  wipe) + upsert_idempotence face via idempotent double-delete]
Oracle: P1 -> both deletes of [9001,9002] return HTTP 200 and exact count
  stays 8 (non-200 on non-existent ids contradicts the idempotent-success
  promise — Type4_StateLogicViolation; 5xx with /healthz alive =
  Type3_RuntimeFailure); D2 -> filter-delete 200, exact count == 4,
  batch-get ids == {4,5,6,7}, GET id 1 -> 404, GET id 5 -> 200 (zombie or
  vanished survivor = Type4_StateLogicViolation); D3a -> 200 and count ==
  0 and batch-get == [] (survivor = Type4); D3b -> {"filter": {}} returns
  200 and count == 0 (400/rejection contradicts "empty filter matches
  everything" — Type4; 200 with survivors = Type4); transport failure ->
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

# URLs used VERBATIM from raw_knowledge api_endpoints[]:
#   {"endpoint_name": "Delete Points", "method": "POST",
#    "url": "/collections/{collection_name}/points/delete"}        -> runtime delete_points
#   {"endpoint_name": "Retrieve Points (batch get)", "method": "POST",
#    "url": "/collections/{collection_name}/points"}               -> get_points_by_ids
# runtime PATHS already carries delete_points/get_point/count verbatim; only the
# POST batch-get face needs registration (runtime has no POST key on that URL).
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


def upsert(coll, points):
    s, raw = safe_request("PUT", "upsert_points",
                          path_params={"name": coll},
                          body={"points": points},
                          query_params={"wait": "true"})
    print(f"[upsert {len(points)} pts] status={s} raw={str(raw)[:160]}")
    if s == 0 or 500 <= s <= 599:
        if s == 0 and not liveness("upsert"):
            ABORT[0] = True
        elif 500 <= s <= 599 and liveness("upsert"):
            DEFECTS.append(f"(setup) upsert returned {s} with service alive "
                           f"— Type3_RuntimeFailure — raw={str(raw)[:150]}")
        else:
            ABORT[0] = True
        return False
    return s == 200


def delete_ids(tag, coll, ids, expect=200):
    s, raw = safe_request("POST", "delete_points",
                          path_params={"name": coll},
                          body={"points": ids},
                          query_params={"wait": "true"})
    print(f"[{tag} delete ids {ids}] status={s} raw={str(raw)[:200]}")
    if s == 0:
        if not liveness(tag):
            ABORT[0] = True
        return s
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) delete returned {s} with service alive "
                           f"— Type3_RuntimeFailure — raw={str(raw)[:150]}")
        else:
            ABORT[0] = True
    elif s != expect:
        DEFECTS.append(f"({tag}) delete of non-existent ids returned {s} "
                       f"(constraint promises idempotent success "
                       f"{expect}) — Type4_StateLogicViolation — "
                       f"raw={str(raw)[:150]}")
    return s


def delete_filter(tag, coll, flt, expect=200):
    s, raw = safe_request("POST", "delete_points",
                          path_params={"name": coll},
                          body={"filter": flt},
                          query_params={"wait": "true"})
    print(f"[{tag} delete filter {json.dumps(flt)[:120]}] status={s} "
          f"raw={str(raw)[:200]}")
    if s == 0:
        if not liveness(tag):
            ABORT[0] = True
        return s
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) filter-delete returned {s} with service "
                           f"alive — Type3_RuntimeFailure — "
                           f"raw={str(raw)[:150]}")
        else:
            ABORT[0] = True
    elif s != expect:
        DEFECTS.append(f"({tag}) filter-delete returned {s} (expected "
                       f"{expect}) — Type4_StateLogicViolation — "
                       f"raw={str(raw)[:150]}")
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
        print(f"SETUP_ERROR: {tag} count result.count missing — "
              f"raw={str(raw)[:200]}")
        return None
    return cnt


def batch_get_ids(tag, coll, ids):
    s, raw = safe_request("POST", "get_points_by_ids",
                          path_params={"collection_name": coll},
                          body={"ids": ids})
    print(f"[{tag} batch-get {len(ids)} ids] status={s} raw={str(raw)[:220]}")
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
        print(f"SETUP_ERROR: {tag} batch-get result not an array — "
              f"raw={str(raw)[:200]}")
        return None
    return [p.get("id") for p in res if isinstance(p, dict)]


def get_point_status(coll, pid):
    s, raw = safe_request("GET", "get_point",
                          path_params={"name": coll, "point_id": pid},
                          query_params={"with_payload": "false"})
    print(f"[get {pid}] status={s} raw={str(raw)[:140]}")
    if s == 0:
        liveness(f"get {pid}")
    elif 500 <= s <= 599:
        if liveness(f"get {pid}"):
            DEFECTS.append(f"(get {pid}) returned {s} with service alive "
                           f"— Type3_RuntimeFailure")
    return s


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spdel1_" + TS + "_"
    C = PFX + "col"
    DIM = 4

    def vec(i):
        return [0.1 + 0.01 * (i % 10), 0.5, 0.75, 1.0]

    def grp_of(i):
        return "a" if i < 4 else "b"

    try:
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        if not upsert(C, [{"id": i, "vector": vec(i),
                           "payload": {"grp": grp_of(i), "n": i}}
                          for i in range(8)]):
            print("SETUP_ERROR: seed upsert failed")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if exact_count("seed", C) != 8:
            print("SETUP_ERROR: seed count != 8")
            return "SCRIPT_ERROR"

        # ---- P1: idempotent delete of never-existing ids (the promise) ----
        s1 = delete_ids("P1a", C, [9001, 9002], expect=200)
        s2 = delete_ids("P1b", C, [9001, 9002], expect=200)
        cnt = exact_count("P1", C)
        if cnt is not None and cnt != 8:
            DEFECTS.append(f"(P1) count {cnt} != 8 after deleting "
                           f"non-existent ids — Type4_StateLogicViolation")
        if s1 == 200 and s2 == 200:
            print("[P1] OK: idempotent non-existent delete returned 200 twice")

        # ---- D2: partial filter-delete with arithmetic oracle ----
        if delete_filter("D2", C, {"must": [{"key": "grp",
                                             "match": {"value": "a"}}]}) != 200:
            print("SETUP_ERROR: D2 filter-delete not 200")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        cnt = exact_count("D2", C)
        if cnt is not None and cnt != 4:
            DEFECTS.append(f"(D2) exact count {cnt} != 8-4=4 after grp=a "
                           f"filter-delete — Type4_StateLogicViolation")
        got = batch_get_ids("D2", C, list(range(8)))
        if got is not None:
            if set(got) != {4, 5, 6, 7}:
                DEFECTS.append(f"(D2) batch-get ids {sorted(set(got))} != "
                               f"[4, 5, 6, 7] — zombie or over-deleted "
                               f"— Type4_StateLogicViolation")
            if len(got) != len(set(got)):
                DEFECTS.append(f"(D2) batch-get returned duplicate ids "
                               f"{got} — Type4_StateLogicViolation")
        st = get_point_status(C, 1)
        if st == 200:
            DEFECTS.append(f"(D2) deleted id 1 still retrievable (200) — "
                           f"zombie — Type4_StateLogicViolation")
        elif st not in (404, 0):
            DEFECTS.append(f"(D2) deleted id 1 GET returned {st} "
                           f"(expected 404) — Type4_StateLogicViolation")
        st = get_point_status(C, 5)
        if st != 200:
            DEFECTS.append(f"(D2) survivor id 5 GET returned {st} "
                           f"(expected 200) — over-deletion — "
                           f"Type4_StateLogicViolation")

        # ---- D3a: structurally matches-all filter wipes everything ----
        if not upsert(C, [{"id": i, "vector": vec(i),
                           "payload": {"grp": "a", "n": i}}
                          for i in range(8, 12)]):
            print("SETUP_ERROR: D3a reseed failed")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if exact_count("D3a-seed", C) != 8:
            print("SETUP_ERROR: D3a reseed count != 8")
            return "SCRIPT_ERROR"
        if delete_filter("D3a", C, {"must": [{"key": "grp",
                                              "match": {"any": ["a", "b"]}}]}) != 200:
            print("SETUP_ERROR: D3a filter-delete not 200")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        cnt = exact_count("D3a", C)
        if cnt is not None and cnt != 0:
            DEFECTS.append(f"(D3a) exact count {cnt} != 0 after matches-all "
                           f"filter wipe — Type4_StateLogicViolation")
        got = batch_get_ids("D3a", C, list(range(12)))
        if got is not None and got:
            DEFECTS.append(f"(D3a) batch-get leaked ids {sorted(set(got))} "
                           f"after matches-all wipe — "
                           f"Type4_StateLogicViolation")

        # ---- D3b: EMPTY filter selector matches everything ----
        if not upsert(C, [{"id": i, "vector": vec(i),
                           "payload": {"grp": "b", "n": i}}
                          for i in range(20, 23)]):
            print("SETUP_ERROR: D3b reseed failed")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if exact_count("D3b-seed", C) != 3:
            print("SETUP_ERROR: D3b reseed count != 3")
            return "SCRIPT_ERROR"
        delete_filter("D3b", C, {})
        cnt = exact_count("D3b", C)
        if cnt is not None and cnt != 0:
            DEFECTS.append(f"(D3b) exact count {cnt} != 0 after empty-filter "
                           f"delete (constraint: empty filter matches "
                           f"everything) — Type4_StateLogicViolation")
        got = batch_get_ids("D3b", C, [20, 21, 22])
        if got is not None and got:
            DEFECTS.append(f"(D3b) batch-get leaked ids {sorted(set(got))} "
                           f"after empty-filter wipe — "
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
