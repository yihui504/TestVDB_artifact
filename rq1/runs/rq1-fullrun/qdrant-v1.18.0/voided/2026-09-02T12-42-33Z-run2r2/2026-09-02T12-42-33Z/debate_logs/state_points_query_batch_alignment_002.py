#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_query_batch_alignment_002
# strategy: count_consistency
# endpoint: points+query+batch
# constraint_ids: qdrant_behavioral_points_query_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/batch-query
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: the 200 face of qdrant_behavioral_points_query_batch_001 —
  "HTTP 200 with ONE RESULT PER SEARCH IN THE SAME ORDER" — exercised
  with a position-sensitive heterogeneous searches array (Strategy 1
  read-consistency / sequence Pattern A). The batch carries 4 searches:
  s0 by-id {1}, s1 nearest, s2 filtered nearest (must/match per contract
  data_types Filter/Match), s3 by-id {6}. Identity probes (unique by-id
  searches) at BOTH ends make the order claim falsifiable without any
  invented ranking/score oracle (R39: score-or-distance oracles are
  refuted; distance-vs-score output semantics are by-design — here only
  point IDs are asserted). Cross-face consistency (G9): the by-id batch
  entries must return the SAME id sets as the equivalent single-face
  POST points/query calls (both are live read-backs). Read-only check:
  exact count must be 6 before AND after the batch (a read face must
  not mutate state; supports qdrant_inv_count_consistency_001).
  [chunk_points+query+batch coverage: count_consistency x
  qdrant_behavioral_points_query_batch_001 (heterogeneous searches
  array: per-search result count + same-order alignment + batch-vs-single
  face id-set equality + read-only count invariance)]
Oracle: batch -> 200 with len(result) == 4 (mismatch = Type4); every
  entry an object with a points list (response_shape: result[].points
  array; violation = Type4); result[0] points contain id 1 and result[3]
  points contain id 6 (order swapped/lost = Type4); result[1]/result[2]
  ids are subsets of the seeded ids {1..6} (unknown id = fabricated
  state, Type4); single-face by-id queries return 200 and their id sets
  equal the batch entries' (face mismatch = Type4); exact count == 6
  before and after (mutation from a read = Type4); 4xx on any valid leg
  = Type4 (assertion pins 200); 5xx with /healthz alive =
  Type3_RuntimeFailure; transport failure -> liveness re-check before
  any verdict.
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
      f"{[k for k in sorted(rt.PATHS) if k in ('query_batch', 'query', 'upsert_points', 'count', 'healthz')]}")

DEFECTS = []
ABORT = [False]

SEED_IDS = list(range(1, 7))
SEED_ID_SET = set(SEED_IDS)

SEARCHES = [
    {"query": 1, "limit": 3},                       # s0 by-id (identity probe)
    {"query": [1.0, 0.0, 0.0, 0.0], "limit": 3},    # s1 nearest
    {"query": [0.0, 1.0, 0.0, 0.0], "limit": 5,     # s2 filtered nearest
     "filter": {"must": [{"key": "grp", "match": {"value": "b"}}]}},
    {"query": 6, "limit": 3},                       # s3 by-id (identity probe)
]


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
    """ids of a per-search result entry; None when the entry violates the shape."""
    if not isinstance(entry, dict):
        return None
    pts = entry.get("points")
    if not isinstance(pts, list):
        return None
    ids = []
    for p in pts:
        if isinstance(p, dict) and "id" in p:
            ids.append(p["id"])
    return ids


def transport_or_5xx(tag, status, raw):
    """Returns True when the leg is judged (defect recorded / abort set)."""
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


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spqb2_" + TS + "_"
    C = PFX + "col"

    def vec(i):
        # distinct, well-separated directions so nearest probes are stable
        v = [0.0, 0.0, 0.0, 0.0]
        v[i % 4] = 1.0
        return v

    try:
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"

        points = [{"id": i, "vector": vec(i),
                   "payload": {"grp": "a" if i % 2 else "b"}}
                  for i in SEED_IDS]
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
                return "DEFECT_FOUND"   # 5xx with service alive recorded
        elif s != 200:
            print(f"SETUP_ERROR: seed upsert returned {s}")
            return "SCRIPT_ERROR"

        cnt_before = exact_count("before", C)
        if cnt_before is None:
            return "SCRIPT_ERROR" if ABORT[0] else "NO_DEFECT"
        if cnt_before != len(SEED_IDS):
            DEFECTS.append(f"(seed) exact count {cnt_before} != "
                           f"{len(SEED_IDS)} after wait=true upsert — "
                           f"Type4_StateLogicViolation "
                           f"(qdrant_inv_count_consistency_001)")

        # ---- the heterogeneous batch ----
        s, raw = safe_request("POST", "query_batch",
                              path_params={"collection_name": C},
                              body={"searches": SEARCHES})
        print(f"[4-search batch] status={s} raw={str(raw)[:500]}")
        if transport_or_5xx("batch", s, raw):
            pass
        elif s != 200:
            DEFECTS.append(f"(batch) heterogeneous all-valid batch query "
                           f"returned {s} — assertion pins 200 with one "
                           f"result per search — Type4_StateLogicViolation")
        else:
            res = result_of(raw)
            if not isinstance(res, list):
                DEFECTS.append("(batch) 200 result is not an array — "
                               "Type4_StateLogicViolation")
            else:
                if len(res) != len(SEARCHES):
                    DEFECTS.append(f"(batch) 200 batch returned {len(res)} "
                                   f"entries for {len(SEARCHES)} searches — "
                                   f"one result per search required — "
                                   f"Type4_StateLogicViolation")
                ids_per_entry = []
                for i, entry in enumerate(res):
                    ids = entry_ids(entry)
                    if ids is None:
                        DEFECTS.append(f"(batch) result[{i}] violates "
                                       f"response_shape (object with points "
                                       f"array): {str(entry)[:100]} — "
                                       f"Type4_StateLogicViolation")
                        ids_per_entry.append(None)
                        continue
                    ids_per_entry.append(ids)
                    unknown = [x for x in ids if x not in SEED_ID_SET]
                    if unknown:
                        DEFECTS.append(f"(batch) result[{i}] returned "
                                       f"non-seeded ids {unknown} — "
                                       f"fabricated state — "
                                       f"Type4_StateLogicViolation")
                # order/alignment via identity probes at both ends
                if len(ids_per_entry) == len(SEARCHES):
                    if ids_per_entry[0] is not None and 1 not in ids_per_entry[0]:
                        DEFECTS.append("(order) result[0] (by-id search of "
                                       "id 1) does not contain id 1 — "
                                       "same-order alignment broken — "
                                       "Type4_StateLogicViolation")
                    if ids_per_entry[3] is not None and 6 not in ids_per_entry[3]:
                        DEFECTS.append("(order) result[3] (by-id search of "
                                       "id 6) does not contain id 6 — "
                                       "same-order alignment broken — "
                                       "Type4_StateLogicViolation")
                    if ids_per_entry[0] is not None and 6 in ids_per_entry[0]:
                        DEFECTS.append("(order) result[0] contains id 6 — "
                                       "entries appear swapped — "
                                       "Type4_StateLogicViolation")
                    if ids_per_entry[3] is not None and 1 in ids_per_entry[3]:
                        DEFECTS.append("(order) result[3] contains id 1 — "
                                       "entries appear swapped — "
                                       "Type4_StateLogicViolation")
                    if ids_per_entry[1] is not None and not ids_per_entry[1]:
                        DEFECTS.append("(batch) result[1] (nearest on 6 "
                                       "seeded points, limit 3) returned an "
                                       "empty points list — "
                                       "Type4_StateLogicViolation")
                # cross-face: single-query equivalents of s0/s3
                for pos, pid in ((0, 1), (3, 6)):
                    s_q, raw_q = safe_request("POST", "query",
                                              path_params={"name": C},
                                              body={"query": pid, "limit": 3})
                    print(f"[single-face by-id {pid}] status={s_q} "
                          f"raw={str(raw_q)[:240]}")
                    if transport_or_5xx(f"single-{pid}", s_q, raw_q):
                        continue
                    if s_q != 200:
                        DEFECTS.append(f"(face) single-face by-id query of "
                                       f"live id {pid} returned {s_q} — "
                                       f"assertion family pins 200 — "
                                       f"Type4_StateLogicViolation")
                        continue
                    single = result_of(raw_q)
                    s_ids = entry_ids(single) if isinstance(single, dict) else None
                    b_ids = (ids_per_entry[pos]
                             if pos < len(ids_per_entry) else None)
                    if s_ids is None or b_ids is None:
                        print(f"[face] by-id {pid}: unreadable id set "
                              f"(single={s_ids!r}, batch={b_ids!r}) — "
                              f"recorded, no claim")
                        continue
                    if set(s_ids) != set(b_ids):
                        DEFECTS.append(f"(face) by-id {pid}: batch entry id "
                                       f"set {sorted(set(b_ids))} != single-"
                                       f"face id set {sorted(set(s_ids))} — "
                                       f"face inconsistency — "
                                       f"Type4_StateLogicViolation")

        # read-only face must not mutate state
        cnt_after = exact_count("after", C)
        if cnt_after is not None and cnt_after != len(SEED_IDS):
            DEFECTS.append(f"(read-only) exact count changed across the "
                           f"batch query: before={cnt_before} "
                           f"after={cnt_after} — read face mutated state — "
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
