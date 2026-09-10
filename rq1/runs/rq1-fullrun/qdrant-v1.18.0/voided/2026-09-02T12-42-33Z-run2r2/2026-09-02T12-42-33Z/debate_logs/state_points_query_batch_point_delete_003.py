#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_query_batch_point_delete_003
# strategy: delete_consistency
# endpoint: points+query+batch
# constraint_ids: qdrant_behavioral_points_query_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/batch-query
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: point-level post-DELETE consistency on the batch query face
  (Strategy 2: post-DELETE consistency) x
  qdrant_behavioral_points_query_batch_001 ("200 with one result per
  search"). A by-id search dereferences the STORED VECTOR of its point
  (qdrant_state_points_query_001, R39-adjudicated: a deleted id has no
  stored vector, so a by-id lookup of it must not serve that point).
  Legs:
  (P) seed {10,11,12,13} wait=true; count==4 arithmetic; all-live batch
  [by-id 10, 11, 12, 13] -> 200 with len(result)==4 and each entry i
  contains its id (positive control).
  (del) DELETE {12,13} wait=true -> 200; exact count must drop 4->2;
  single GET of 12 -> 404 (corroborating the points are really gone).
  (mixed) batch [by-id 10, by-id 12 (deleted), by-id 11] — per-entry
  error granularity is NOT promised for the batch face (R37: mixed
  batches may legitimately be whole-rejected — verify, don't assume), so
  BOTH dispositions are accepted: whole-batch 4xx (clean rejection,
  recorded) OR 200 with len(result)==3. In the 200 case: entry0 contains
  10, entry2 contains 11 (survivors served), and entry1 must NOT contain
  id 12 — serving the deleted id inside a 200 batch = ghost read
  (Type4). Missing survivors in a 200 = over-deletion (Type4).
  (pos2) survivors-unaffected batch [by-id 10, by-id 11] -> 200 with
  both ids served; final exact count == 2.
  Mutation-point justification (G6): point-level delete empties exactly
  the state slot the by-id search dereferences while every other
  observable stays alive — isolating the ghost-read question on the
  batch face.
  [chunk_points+query+batch coverage: delete_consistency x
  qdrant_behavioral_points_query_batch_001 (mixed live+deleted by-id
  searches: per-entry ghost read + survivor over-deletion + 4->2 count
  arithmetic + whole-reject disposition recording)]
Oracle: (P) all-live batch -> 200, len(result)==4, each entry contains
  its searched id; (del) delete -> 200, exact count == 2, GET 12 -> 404;
  (mixed) whole-batch 4xx accepted and recorded, OR 200 with
  len(result)==3, entry0 contains 10, entry2 contains 11, entry1 free of
  id 12 (id 12 served = ghost read Type4_StateLogicViolation; survivor
  missing = Type4; len mismatch = Type4); (pos2) -> 200 both ids served;
  final count == 2; 5xx with /healthz alive = Type3_RuntimeFailure;
  transport failure -> liveness re-check before any verdict.
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
#   {"path": "points+query+batch", "method": "POST",
#    "url": "/collections/{collection_name}/points/query/batch"}
rt.PATHS["query_batch"] = "/collections/{collection_name}/points/query/batch"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if k in ('query_batch', 'upsert_points', 'delete_points', 'get_point', 'count', 'healthz')]}")

DEFECTS = []
ABORT = [False]

LIVE = [10, 11]
DEAD = [12, 13]


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


def entry_ids(entry):
    if not isinstance(entry, dict):
        return None
    pts = entry.get("points")
    if not isinstance(pts, list):
        return None
    return [p.get("id") for p in pts
            if isinstance(p, dict) and "id" in p]


def transport_or_5xx(tag, status, raw):
    if status == 0:
        if not liveness(tag):
            ABORT[0] = True
        return True
    if 500 <= status <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) returned {status} with service alive — "
                           f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
        else:
            ABORT[0] = True
        return True
    return False


def exact_count(tag, coll):
    s, raw = safe_request("POST", "count", path_params={"name": coll},
                          body={"exact": True})
    print(f"[{tag} count] status={s} raw={str(raw)[:160]}")
    if transport_or_5xx(tag + "-count", s, raw):
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


def batch_by_id(tag, coll, ids):
    """Batch of one by-id search per id (in the given order)."""
    searches = [{"query": pid, "limit": 3} for pid in ids]
    s, raw = safe_request("POST", "query_batch",
                          path_params={"collection_name": coll},
                          body={"searches": searches})
    print(f"[{tag} batch by-id {ids}] status={s} raw={str(raw)[:400]}")
    if transport_or_5xx(tag, s, raw):
        return "TRANSPORT"
    return s, raw


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spqb3_" + TS + "_"
    C = PFX + "col"

    try:
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"

        points = [{"id": i, "vector": [float(i % 4 == k) for k in range(4)]}
                  for i in LIVE + DEAD]
        s, raw = safe_request("PUT", "upsert_points",
                              path_params={"name": C},
                              body={"points": points},
                              query_params={"wait": "true"})
        print(f"[seed] status={s} raw={str(raw)[:180]}")
        if s == 0 or 500 <= s <= 599:
            transport_or_5xx("seed", s, raw)
            if ABORT[0]:
                return "SCRIPT_ERROR"
            if DEFECTS:
                return "DEFECT_FOUND"
        elif s != 200:
            print(f"SETUP_ERROR: seed upsert returned {s}")
            return "SCRIPT_ERROR"

        cnt = exact_count("P-seed", C)
        if cnt is not None and cnt != 4:
            DEFECTS.append(f"(P) seed count {cnt} != 4 — "
                           f"Type4_StateLogicViolation")

        # ---- (P) all-live positive control ----
        out = batch_by_id("P", C, LIVE + DEAD)
        if out != "TRANSPORT":
            s, raw = out
            if s != 200:
                DEFECTS.append(f"(P) all-live by-id batch returned {s} — "
                               f"assertion pins 200 with one result per "
                               f"search — Type4_StateLogicViolation")
            else:
                res = result_of(raw)
                if not isinstance(res, list) or len(res) != 4:
                    DEFECTS.append(f"(P) 200 batch result is not a 4-entry "
                                   f"array: {str(res)[:120]} — "
                                   f"Type4_StateLogicViolation")
                else:
                    for i, pid in enumerate(LIVE + DEAD):
                        ids = entry_ids(res[i])
                        if ids is None:
                            DEFECTS.append(f"(P) result[{i}] violates shape — "
                                           f"Type4_StateLogicViolation")
                        elif pid not in ids:
                            DEFECTS.append(f"(P) by-id search of live id "
                                           f"{pid} did not return it "
                                           f"(got {ids}) — "
                                           f"Type4_StateLogicViolation")

        # ---- (del) delete 2 points ----
        s, raw = safe_request("POST", "delete_points",
                              path_params={"name": C},
                              body={"points": DEAD},
                              query_params={"wait": "true"})
        print(f"[del delete {DEAD}] status={s} raw={str(raw)[:200]}")
        if s == 0 or 500 <= s <= 599:
            transport_or_5xx("del", s, raw)
            if ABORT[0]:
                return "SCRIPT_ERROR"
            if DEFECTS:
                return "DEFECT_FOUND"
        elif s != 200:
            print(f"SETUP_ERROR: delete returned {s}")
            return "SCRIPT_ERROR"

        cnt = exact_count("del", C)
        if cnt is not None and cnt != 2:
            DEFECTS.append(f"(del) exact count {cnt} != 2 after deleting 2 "
                           f"of 4 (4->2 arithmetic) — "
                           f"Type4_StateLogicViolation")

        s, raw = safe_request("GET", "get_point",
                              path_params={"name": C, "point_id": 12})
        print(f"[corroborate GET 12] status={s} raw={str(raw)[:160]}")
        if s == 200:
            DEFECTS.append("(corroborate) GET of deleted id 12 returned 200 "
                           "— zombie point — Type4_StateLogicViolation")

        # ---- (mixed) live + deleted by-id searches in one batch ----
        out = batch_by_id("mixed", C, [10, 12, 11])
        if out != "TRANSPORT":
            s, raw = out
            if s != 200:
                if 400 <= s <= 499:
                    print(f"[mixed] whole-batch {s} rejection — accepted "
                          f"disposition (per-entry error granularity is "
                          f"not promised); recorded, no claim")
                else:
                    DEFECTS.append(f"(mixed) batch returned {s} — neither "
                                   f"the pinned 200 nor a clean 4xx "
                                   f"rejection — Type4_StateLogicViolation")
            else:
                res = result_of(raw)
                if not isinstance(res, list) or len(res) != 3:
                    DEFECTS.append(f"(mixed) 200 batch result is not a "
                                   f"3-entry array: {str(res)[:120]} — "
                                   f"Type4_StateLogicViolation")
                else:
                    ids0 = entry_ids(res[0])
                    ids1 = entry_ids(res[1])
                    ids2 = entry_ids(res[2])
                    if ids0 is not None and 10 not in ids0:
                        DEFECTS.append(f"(mixed) entry0 (by-id 10) missing "
                                       f"survivor (got {ids0}) — "
                                       f"over-deletion — "
                                       f"Type4_StateLogicViolation")
                    if ids1 is not None and 12 in ids1:
                        DEFECTS.append(f"(mixed) entry1 served DELETED id 12 "
                                       f"(got {ids1}) — ghost read — "
                                       f"Type4_StateLogicViolation")
                    if ids2 is not None and 11 not in ids2:
                        DEFECTS.append(f"(mixed) entry2 (by-id 11) missing "
                                       f"survivor (got {ids2}) — "
                                       f"over-deletion — "
                                       f"Type4_StateLogicViolation")

        # ---- (pos2) survivors unaffected ----
        out = batch_by_id("pos2", C, LIVE)
        if out != "TRANSPORT":
            s, raw = out
            if s != 200:
                DEFECTS.append(f"(pos2) survivor-only batch returned {s} — "
                               f"assertion pins 200 — "
                               f"Type4_StateLogicViolation")
            else:
                res = result_of(raw)
                if not isinstance(res, list) or len(res) != 2:
                    DEFECTS.append(f"(pos2) 200 batch result is not a "
                                   f"2-entry array — "
                                   f"Type4_StateLogicViolation")
                else:
                    for i, pid in enumerate(LIVE):
                        ids = entry_ids(res[i])
                        if ids is not None and pid not in ids:
                            DEFECTS.append(f"(pos2) by-id search of survivor "
                                           f"{pid} did not return it "
                                           f"(got {ids}) — "
                                           f"Type4_StateLogicViolation")

        cnt = exact_count("final", C)
        if cnt is not None and cnt != 2:
            DEFECTS.append(f"(final) exact count {cnt} != 2 — "
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
