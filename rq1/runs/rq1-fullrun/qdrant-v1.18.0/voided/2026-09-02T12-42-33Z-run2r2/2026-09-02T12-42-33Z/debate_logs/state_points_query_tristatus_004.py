#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_query_tristatus_004
# strategy: delete_consistency
# endpoint: points+query
# constraint_ids: qdrant_behavioral_points_query_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: query-points tri-status contract (200/400/404) with collection
  lifecycle (Strategy 2: post-DELETE consistency + Pattern B/C lifecycle)
  x qdrant_behavioral_points_query_001 "valid query returns HTTP 200 with
  result array of scored points and optional next_page_offset; invalid
  query returns 400; missing collection returns 404". Legs:
  (404-pre) query against a never-created collection name -> 404.
  (200) after create+seed, a valid nearest query -> 200 AND the envelope
  must be result.points array per the v1.18 published response_shape
  (shape oracle cross-checked against the OpenAPI-derived contract, not
  the older bare result array).
  (400a) invalid query variant {"query": {"bogus_variant": 1}} -> 400.
  (400b) invalid query type {"query": "not-a-query"} (bare string is not
  a Query variant: neither id, nor float array, nor variant struct) ->
  400. 2xx on either = illegal success; 422 = correct rejection but
  status deviates from the pinned 400 (recorded as WARN, not a state
  defect).
  (404-post) DELETE the collection (wait) -> query must return 404 (200 =
  zombie collection read path; 5xx = internal error). Corroborated by
  describe -> 404 and the name absent from the collections list.
  Mutation-point justification (G6): collection drop is the lifecycle
  mutation that flips the 200 face to the 404 face of the SAME request —
  the only mutation that isolates per-collection routing state from the
  query path itself.
  [chunk_points+query coverage: delete_consistency x
  qdrant_behavioral_points_query_001 (never-existing 404 + valid 200
  shape + invalid 400 x2 + post-drop 404 + describe/list corroboration)]
Oracle: (404-pre) -> 404; (200) -> HTTP 200 with result object containing
  a points array; (400a/400b) -> HTTP 400 (2xx = Type1_IllegalSuccess;
  422 = rejection accepted with WARN note); (404-post) -> 404 — 200 =
  zombie collection (Type4_StateLogicViolation); describe 404 + list
  absence corroborate; 5xx with /healthz alive = Type3_RuntimeFailure;
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

print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if k in ('query', 'upsert_points', 'drop_collection', 'describe_collection', 'list_collections')]}")

DEFECTS = []
WARNINGS = []
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


def handle_transport(tag, status, raw):
    if status == 0:
        if not liveness(tag):
            ABORT[0] = True
        return True
    if 500 <= status <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) returned {status} with service alive "
                           f"— Type3_RuntimeFailure — raw={str(raw)[:150]}")
        else:
            ABORT[0] = True
        return True
    return False


def query_call(tag, coll, body):
    s, raw = safe_request("POST", "query", path_params={"name": coll}, body=body)
    print(f"[{tag}] status={s} raw={str(raw)[:240]}")
    if handle_transport(tag, s, raw):
        return s, raw, None
    return s, raw, raw


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spq4_" + TS + "_"
    C = PFX + "col"
    C_GHOST = PFX + "never"   # never created
    DIM = 4

    try:
        # ---- 404-pre: missing collection (never created) ----
        s, raw, _ = query_call("404-pre-never-existing", C_GHOST,
                               {"query": [0.1, 0.2, 0.3, 0.4], "limit": 3})
        if s is not None and s > 0:
            if s != 404:
                DEFECTS.append(f"(404-pre) query on never-existing collection "
                               f"returned {s} (spec: missing collection -> 404) "
                               f"— Type4_StateLogicViolation — raw={str(raw)[:150]}")
            else:
                print("[404-pre] OK: never-existing collection -> 404")

        # ---- setup ----
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        s_up, raw_up = safe_request("PUT", "upsert_points",
                                    path_params={"name": C},
                                    body={"points": [
                                        {"id": 1, "vector": [1.0, 0.0, 0.0, 0.0]},
                                        {"id": 2, "vector": [0.9, 0.1, 0.0, 0.0]},
                                        {"id": 3, "vector": [0.0, 1.0, 0.0, 0.0]},
                                    ]},
                                    query_params={"wait": "true"})
        print(f"[seed upsert] status={s_up} raw={str(raw_up)[:160]}")
        if handle_transport("seed upsert", s_up, raw_up) or s_up != 200:
            print("SETUP_ERROR: seed upsert failed")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"

        # ---- 200: valid query + envelope shape (result.points array) ----
        s, raw, _ = query_call("200-valid", C,
                               {"query": [1.0, 0.0, 0.0, 0.0], "limit": 3})
        if s == 200:
            try:
                res = json.loads(raw).get("result")
            except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
                res = None
            pts = res.get("points") if isinstance(res, dict) else None
            if not isinstance(pts, list) or not pts:
                DEFECTS.append(f"(200) valid query 200 but result.points is not "
                               f"a non-empty array (contract response_shape: "
                               f"result object with points array of ScoredPoint) "
                               f"— raw={str(raw)[:150]}")
            else:
                first = pts[0]
                if not isinstance(first, dict) or "id" not in first:
                    DEFECTS.append(f"(200) result.points[0] lacks id field — "
                                   f"raw={str(raw)[:150]}")
                else:
                    print(f"[200] OK: valid query -> 200, {len(pts)} scored "
                          f"points, top id={first.get('id')}")
        elif s is not None and s > 0:
            DEFECTS.append(f"(200) valid query returned {s} (spec promises "
                           f"200) — Type4_StateLogicViolation — "
                           f"raw={str(raw)[:150]}")

        # ---- 400a: unknown query variant key ----
        s, raw, _ = query_call("400a-bogus-variant", C,
                               {"query": {"bogus_variant": 1}, "limit": 3})
        if s is not None and s > 0:
            if 200 <= s <= 299:
                DEFECTS.append(f"(400a) invalid query (unknown variant) "
                               f"returned {s} — Type1_IllegalSuccess — "
                               f"raw={str(raw)[:150]}")
            elif s == 400:
                print("[400a] OK: invalid variant -> 400")
            elif 400 <= s <= 499:
                WARNINGS.append(f"(400a) invalid query rejected with {s} "
                                f"(spec pins 400; rejection itself is correct)")
                print(f"[400a] WARN: rejected with {s} instead of pinned 400")
            else:
                DEFECTS.append(f"(400a) invalid query returned unexpected "
                               f"{s} — raw={str(raw)[:150]}")

        # ---- 400b: bare string is not a Query ----
        s, raw, _ = query_call("400b-string-query", C,
                               {"query": "not-a-query", "limit": 3})
        if s is not None and s > 0:
            if 200 <= s <= 299:
                DEFECTS.append(f"(400b) invalid query (bare string) returned "
                               f"{s} — Type1_IllegalSuccess — "
                               f"raw={str(raw)[:150]}")
            elif s == 400:
                print("[400b] OK: string query -> 400")
            elif 400 <= s <= 499:
                WARNINGS.append(f"(400b) bare-string query rejected with {s} "
                                f"(spec pins 400; rejection itself is correct)")
                print(f"[400b] WARN: rejected with {s} instead of pinned 400")
            else:
                DEFECTS.append(f"(400b) invalid query returned unexpected "
                               f"{s} — raw={str(raw)[:150]}")

        # ---- 404-post: drop the collection, then query ----
        s_d, raw_d = safe_request("DELETE", "drop_collection",
                                  path_params={"name": C})
        print(f"[drop] status={s_d} raw={str(raw_d)[:160]}")
        if handle_transport("drop", s_d, raw_d) or s_d != 200:
            print("SETUP_ERROR: drop not 200")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"

        s, raw, _ = query_call("404-post-deleted", C,
                               {"query": [1.0, 0.0, 0.0, 0.0], "limit": 3})
        if s is not None and s > 0:
            if s != 404:
                DEFECTS.append(f"(404-post) query on DELETED collection "
                               f"returned {s} (spec: missing collection -> 404; "
                               f"200 = zombie read path) — "
                               f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
            else:
                print("[404-post] OK: deleted collection -> 404")

        # corroboration: describe -> 404, list -> name absent
        s_desc, raw_desc = safe_request("GET", "describe_collection",
                                        path_params={"name": C})
        print(f"[describe after drop] status={s_desc} raw={str(raw_desc)[:140]}")
        if s_desc is not None and s_desc > 0 and s_desc != 404:
            DEFECTS.append(f"(404-post) describe of deleted collection returned "
                           f"{s_desc} (expected 404) — "
                           f"Type4_StateLogicViolation")
        s_ls, raw_ls = safe_request("GET", "list_collections")
        print(f"[list after drop] status={s_ls} raw={str(raw_ls)[:200]}")
        if s_ls == 200:
            try:
                names = [e.get("name") for e in
                         (json.loads(raw_ls).get("result") or {}).get("collections", [])
                         if isinstance(e, dict)]
            except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
                names = None
            if names is not None and C in names:
                DEFECTS.append("(404-post) deleted collection still listed in "
                               "collections list — Type4_StateLogicViolation")

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
