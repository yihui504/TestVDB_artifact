#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_query_batch_index_toggle_007
# strategy: index_state
# endpoint: points+query+batch
# constraint_ids: qdrant_behavioral_points_query_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/batch-query
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: state consistency across a payload-index lifecycle, observed
  through the batch query face (Strategy 6: state consistency during
  index changes) x qdrant_behavioral_points_query_batch_001 ("200 with
  one result per search") + the system invariant
  qdrant_inv_index_toggle_preserves_data_001 ("creating and deleting a
  payload index does not alter point data"). The batch face is the
  observation instrument: the IDENTICAL searches array (5 by-id searches
  limit 1 + 1 nearest search) is fired at three states of the same
  collection — (B0) before any payload index, (B1) after PUT index on
  the payload field "city" (keyword, wait=true), (B2) after DELETE index
  (wait=true). The invariant promises the observables are unchanged by
  the toggle, so the per-entry id sets of B1 and B2 must EQUAL B0's
  (relative comparison — robust to whatever the baseline disposition is,
  and no absolute content claim is made beyond the assertion's own
  one-result-per-search promise, which must hold in every phase).
  HNSW approximate-search nondeterminism is by-design, so id-set
  equality is only asserted for the by-id searches of live ids at
  limit 1 (the referenced point is the unique distance-0 result for its
  own orthogonal vector); the nearest entry gets shape checks only.
  Exact count must be 5 in every phase (the toggle must neither drop
  nor duplicate points).
  [chunk_points+query+batch coverage: index_state x
  qdrant_behavioral_points_query_batch_001 (payload index create/drop
  toggle x identical batch queries: B0==B1==B2 id-set equality + count
  invariance + one-result-per-search in every phase)]
Oracle: every batch (B0/B1/B2) -> 200 with len(result) == 6 (violation
  = Type4_StateLogicViolation against the assertion); per-entry by-id id
  sets of B1 and B2 equal B0's exactly (divergence = the index toggle
  altered observable point state — Type4_StateLogicViolation,
  qdrant_inv_index_toggle_preserves_data_001); exact count == 5 in every
  phase (mismatch = Type4); index create/delete returning 4xx = WARN
  (acceptance belongs to the index chunk; the toggle comparison remains
  valid); 5xx with /healthz alive = Type3_RuntimeFailure; transport
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

# URLs registered VERBATIM from raw_knowledge api_endpoints[]:
#   {"path": "points+query+batch", "method": "POST",
#    "url": "/collections/{collection_name}/points/query/batch"}
rt.PATHS["query_batch"] = "/collections/{collection_name}/points/query/batch"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if k in ('query_batch', 'create_index', 'delete_index', 'upsert_points', 'count', 'healthz')]}")

DEFECTS = []
WARNINGS = []
ABORT = [False]

SEED_IDS = [1, 2, 3, 4, 5]
INDEX_FIELD = "city"

# 5 by-id searches (limit 1: the referenced point is the unique
# distance-0 result for its own orthogonal vector) + 1 nearest search
SEARCHES = [{"query": pid, "limit": 1} for pid in SEED_IDS] + \
           [{"query": [0.7, 0.7, 0.0, 0.0], "limit": 3}]


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


def batch_snapshot(tag, coll):
    """Fire the IDENTICAL searches array; return per-entry id sets or None."""
    s, raw = safe_request("POST", "query_batch",
                          path_params={"collection_name": coll},
                          body={"searches": SEARCHES})
    print(f"[{tag} batch] status={s} raw={str(raw)[:400]}")
    if transport_or_5xx(tag, s, raw):
        return None
    if s != 200:
        DEFECTS.append(f"({tag}) batch query returned {s} — assertion pins "
                       f"200 with one result per search — "
                       f"Type4_StateLogicViolation")
        return None
    res = result_of(raw)
    if not isinstance(res, list):
        DEFECTS.append(f"({tag}) 200 result is not an array — "
                       f"Type4_StateLogicViolation")
        return None
    if len(res) != len(SEARCHES):
        DEFECTS.append(f"({tag}) 200 batch returned {len(res)} entries for "
                       f"{len(SEARCHES)} searches — one result per search "
                       f"required — Type4_StateLogicViolation")
    id_sets = []
    for i, entry in enumerate(res):
        ids = entry_ids(entry)
        if ids is None:
            DEFECTS.append(f"({tag}) result[{i}] violates response_shape "
                           f"(object with points array) — "
                           f"Type4_StateLogicViolation")
            id_sets.append(None)
        else:
            id_sets.append(ids)
    return id_sets


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spqb7_" + TS + "_"
    C = PFX + "col"

    try:
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"

        points = []
        for i in SEED_IDS:
            v = [0.0] * 4
            v[(i - 1) % 4] = 1.0
            points.append({"id": i, "vector": v,
                           "payload": {INDEX_FIELD: "x" if i % 2 else "y"}})
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

        cnt0 = exact_count("B0", C)
        if cnt0 is not None and cnt0 != len(SEED_IDS):
            DEFECTS.append(f"(B0) seed count {cnt0} != {len(SEED_IDS)} — "
                           f"Type4_StateLogicViolation")

        # ---- B0: before any payload index ----
        b0 = batch_snapshot("B0", C)
        if b0 is None:
            if ABORT[0]:
                return "SCRIPT_ERROR"
            return "DEFECT_FOUND" if DEFECTS else "SCRIPT_ERROR"
        for i, pid in enumerate(SEED_IDS):
            if b0[i] is not None and pid not in b0[i]:
                WARNINGS.append(f"(B0) by-id search of {pid} (limit 1) "
                                f"returned ids {b0[i]} — baseline recorded; "
                                f"the toggle claim compares phases relative "
                                f"to this baseline")

        # ---- create payload index on "city" ----
        s, raw = safe_request("PUT", "create_index",
                              body={"field_name": INDEX_FIELD,
                                    "field_schema": "keyword"},
                              path_params={"name": C},
                              query_params={"wait": "true"})
        print(f"[create index {INDEX_FIELD}=keyword] status={s} "
              f"raw={str(raw)[:200]}")
        if s != 200 and not transport_or_5xx("create-index", s, raw):
            if 400 <= s <= 499:
                WARNINGS.append(f"(index) create returned {s} — acceptance "
                                f"belongs to the index chunk; toggle "
                                f"comparison continues on the un-indexed "
                                f"state (B1==B0 then verifies the no-op)")

        # ---- B1: with the payload index ----
        b1 = batch_snapshot("B1", C)
        cnt1 = exact_count("B1", C)
        if cnt1 is not None and cnt1 != len(SEED_IDS):
            DEFECTS.append(f"(B1) count {cnt1} != {len(SEED_IDS)} after "
                           f"index create — index toggle altered point "
                           f"population — Type4_StateLogicViolation "
                           f"(qdrant_inv_index_toggle_preserves_data_001)")

        # ---- delete the payload index ----
        s, raw = safe_request("DELETE", "delete_index",
                              path_params={"name": C,
                                           "field_name": INDEX_FIELD},
                              query_params={"wait": "true"})
        print(f"[delete index {INDEX_FIELD}] status={s} raw={str(raw)[:200]}")
        if s != 200 and not transport_or_5xx("delete-index", s, raw):
            if 400 <= s <= 499:
                WARNINGS.append(f"(index) delete returned {s} — recorded; "
                                f"B2 still observes the post-toggle state")

        # ---- B2: after the index drop ----
        b2 = batch_snapshot("B2", C)
        cnt2 = exact_count("B2", C)
        if cnt2 is not None and cnt2 != len(SEED_IDS):
            DEFECTS.append(f"(B2) count {cnt2} != {len(SEED_IDS)} after "
                           f"index delete — index toggle altered point "
                           f"population — Type4_StateLogicViolation "
                           f"(qdrant_inv_index_toggle_preserves_data_001)")

        # ---- phase equality (the invariant claim) ----
        for tag, later in (("B1", b1), ("B2", b2)):
            if later is None or b0 is None:
                continue
            for i in range(min(len(b0), len(later))):
                if b0[i] is None or later[i] is None:
                    continue
                if i < len(SEED_IDS) and sorted(b0[i]) != sorted(later[i]):
                    DEFECTS.append(f"({tag}) by-id entry {i} id set changed "
                                   f"across the index toggle: B0={b0[i]} "
                                   f"{tag}={later[i]} — index lifecycle "
                                   f"altered observable point state — "
                                   f"Type4_StateLogicViolation "
                                   f"(qdrant_inv_index_toggle_preserves_"
                                   f"data_001)")

        for w in WARNINGS:
            print(f"WARN: {w}")
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
