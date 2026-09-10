#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_percol_create_queryable_001
# strategy: create_visibility_contract
# endpoint: per_collection
# constraint_ids: qdrant_inv_create_queryable_001
# source_url: https://qdrant.tech/documentation/manage-data/collections/
# doc_version: current (site latest; no version archive)
"""
Attack: create_visibility_contract (lifecycle Pattern A start: the negative
  pre-state grounds the positive promise) x qdrant_inv_create_queryable_001
  "after a successful create the collection is queryable" whose assertion
  pins THREE queryable faces: (a) name appears in the collections list and
  details, (b) exists reports result.exists=true, (c) queries against the
  name return 200. This script exercises every access face in one sequence
  on one freshly created collection and adjudicates CROSS-FACE consistency
  (G9): after a single successful PUT create, all faces must agree the
  collection exists and is usable; a face-pair disagreement (exists=true
  while list/describe/count/scroll/query says 404, or any face 5xx) is a
  state-logic violation. Sequence: (pre) fresh unique name -> exists=false
  AND describe=404 (negative pre-state); (create) PUT /collections/{name}
  with vectors config -> 200; (post faces) list contains name, describe
  200, exists result.exists=true, count 200 with result.count=0, scroll
  200 with empty points, query nearest 200; (data face) upsert 1 point
  wait=true -> 200, count=1, batch get + single get both return the point.
  [chunk_per_collection coverage: create_visibility_contract x
  qdrant_inv_create_queryable_001 (all queryable faces + negative
  pre-state + data-carrying face)]
Oracle: pre-create: exists -> 200 with result.exists=false and describe ->
  404; create -> 200; post-create every face returns 200 with the queried
  name visible (list contains it, result.exists=true, result.count=0 on a
  fresh collection); any post-create 404 while exists=true, or any face
  5xx with /healthz alive = defect (404-face = Type4_StateLogicViolation
  cross-face inconsistency, 5xx = Type3_RuntimeFailure); upsert -> 200 and
  count transitions 0 -> 1 exactly.
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

# collections+exists is not in the runtime PATHS whitelist — register
# VERBATIM from raw_knowledge api_endpoints[].url:
#   {"path": "collections+exists", "method": "GET",
#    "url": "/collections/{collection_name}/exists"}
rt.PATHS["exists_collection"] = "/collections/{collection_name}/exists"
# points+get (batch) is not in the whitelist — register VERBATIM:
#   {"path": "points+get", "method": "POST",
#    "url": "/collections/{collection_name}/points/get"}
rt.PATHS["get_points"] = "/collections/{collection_name}/points/get"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if k in ('exists_collection', 'get_points')]}")

DEFECTS = []
ABORT = [False]


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
    print(f"[liveness {tag}] healthz probe required")
    _hs, _hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={_hs} raw={str(_hraw)[:120]}")
    return _hs == 200


def classify(tag, status, raw, expect_ok, defect_kind="Type4_StateLogicViolation"):
    """Shared adjudication: transport -> liveness; 5xx alive -> Type3;
    unexpected status on a must-work face -> recorded defect."""
    label = f"({tag}) {defect_kind}" if defect_kind else f"({tag})"
    if status == 0:
        if not liveness(tag):
            ABORT[0] = True
        else:
            DEFECTS.append(f"{label} transport failure with service alive — "
                           f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
        return "fail"
    if 500 <= status <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) returned {status} with service alive — "
                           f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
        else:
            ABORT[0] = True
        return "fail"
    if expect_ok == "200" and status != 200:
        DEFECTS.append(f"({tag}) expected 200 on the queryable face, got "
                       f"{status} — {defect_kind} — raw={str(raw)[:150]}")
        return "fail"
    return "ok"


def result_of(raw):
    try:
        r = json.loads(raw).get("result")
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        return None
    return r


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spcq1_" + TS + "_"
    C = PFX + "col"
    DIM = 4

    try:
        # ---- (pre negative state: not-yet-created must be non-queryable) ----
        s, raw = safe_request("GET", "exists_collection",
                              path_params={"collection_name": C})
        print(f"[pre exists] status={s} raw={raw[:160]}")
        if classify("pre exists", s, raw, "200") == "ok":
            res = result_of(raw)
            ex = res.get("exists") if isinstance(res, dict) else None
            if ex is not True and ex is not False:
                print(f"SETUP_ERROR: pre exists result.exists not bool: {res!r}")
                return "SCRIPT_ERROR"
            if ex is True:
                DEFECTS.append("(pre exists) fresh unique name reports "
                               f"result.exists=true before any create — "
                               f"Type4_StateLogicViolation")
            else:
                print("[pre exists] OK: exists=false before create")
        s, raw = safe_request("GET", "describe_collection",
                              path_params={"name": C})
        print(f"[pre describe] status={s} raw={raw[:160]}")
        if s == 200:
            DEFECTS.append("(pre describe) fresh unique name is describable "
                           "before create — Type4_StateLogicViolation")

        # ---- (create) ----
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        print("[create] OK via setup_default (PUT /collections/{name})")

        # ---- (post faces) ----
        s, raw = safe_request("GET", "exists_collection",
                              path_params={"collection_name": C})
        print(f"[post exists] status={s} raw={raw[:160]}")
        if classify("post exists", s, raw, "200") == "ok":
            res = result_of(raw)
            ex = res.get("exists") if isinstance(res, dict) else None
            if ex is not True:
                DEFECTS.append("(post exists) after successful create "
                               f"result.exists={ex!r} (expected true) — "
                               f"Type4_StateLogicViolation")

        s, raw = safe_request("GET", "describe_collection",
                              path_params={"name": C})
        print(f"[post describe] status={s} raw={raw[:160]}")
        classify("post describe", s, raw, "200")

        s, raw = safe_request("GET", "list_collections")
        print(f"[post list] status={s} raw={raw[:200]}")
        if classify("post list", s, raw, "200") == "ok":
            res = result_of(raw)
            cols = res.get("collections") if isinstance(res, dict) else None
            names = [c.get("name") for c in cols
                     if isinstance(c, dict)] if isinstance(cols, list) else []
            if C not in names:
                DEFECTS.append("(post list) created collection absent from "
                               f"collections list (names={names[:10]}...) — "
                               f"Type4_StateLogicViolation")
            else:
                print("[post list] OK: name present")

        s, raw = safe_request("POST", "count", path_params={"name": C},
                              body={"exact": True})
        print(f"[post count] status={s} raw={raw[:160]}")
        if classify("post count", s, raw, "200") == "ok":
            res = result_of(raw)
            cnt = res.get("count") if isinstance(res, dict) else None
            if cnt != 0:
                DEFECTS.append("(post count) fresh collection exact count "
                               f"= {cnt!r} (expected 0) — "
                               f"Type4_StateLogicViolation")
            else:
                print("[post count] OK: count=0 on fresh collection")

        s, raw = safe_request("POST", "scroll", path_params={"name": C},
                              body={"limit": 10, "with_payload": True})
        print(f"[post scroll] status={s} raw={raw[:160]}")
        if classify("post scroll", s, raw, "200") == "ok":
            res = result_of(raw)
            pts = res.get("points") if isinstance(res, dict) else None
            if pts != []:
                DEFECTS.append("(post scroll) fresh collection scroll "
                               f"points={pts!r} (expected []) — "
                               f"Type4_StateLogicViolation")
            else:
                print("[post scroll] OK: empty points")

        s, raw = safe_request("POST", "query", path_params={"name": C},
                              body={"query": {"nearest": [0.1] * DIM},
                                    "limit": 1})
        print(f"[post query] status={s} raw={raw[:160]}")
        if classify("post query", s, raw, "200") == "ok":
            res = result_of(raw)
            pts = res.get("points") if isinstance(res, dict) else None
            if not isinstance(pts, list):
                DEFECTS.append("(post query) result.points missing on the "
                               f"queryable face — raw={str(raw)[:150]} — "
                               f"Type4_StateLogicViolation")
            else:
                print(f"[post query] OK: 200, points={len(pts)}")

        # ---- (data face: upsert then retrieve) ----
        pt = {"id": 1, "vector": [1.0, 2.0, 3.0, 4.0],
              "payload": {"city": "berlin", "n": 1}}
        s, raw = safe_request("PUT", "upsert_points",
                              path_params={"name": C}, body={"points": [pt]},
                              query_params={"wait": "true"})
        print(f"[data upsert] status={s} raw={raw[:160]}")
        if classify("data upsert", s, raw, "200") == "ok":
            s2, raw2 = safe_request("POST", "count",
                                    path_params={"name": C},
                                    body={"exact": True})
            if classify("post-data count", s2, raw2, "200") == "ok":
                cnt = result_of(raw2)
                cnt = cnt.get("count") if isinstance(cnt, dict) else None
                if cnt != 1:
                    DEFECTS.append(f"(post-data count) count={cnt!r} after "
                                   f"1 upsert (expected 1) — "
                                   f"Type4_StateLogicViolation")
                else:
                    print("[post-data count] OK: count=1")

        s, raw = safe_request("POST", "get_points",
                              path_params={"collection_name": C},
                              body={"ids": [1], "with_payload": True})
        print(f"[data batch get] status={s} raw={raw[:200]}")
        if classify("data batch get", s, raw, "200") == "ok":
            res = result_of(raw)
            got = res if isinstance(res, list) else None
            if not isinstance(got, list) or len(got) != 1 \
                    or (got[0] or {}).get("id") != 1:
                DEFECTS.append("(data batch get) point 1 not returned — "
                               f"raw={str(raw)[:150]} — "
                               f"Type4_StateLogicViolation")
            else:
                print("[data batch get] OK: point 1 present")

        s, raw = safe_request("GET", "get_point",
                              path_params={"name": C, "point_id": 1})
        print(f"[data single get] status={s} raw={raw[:200]}")
        classify("data single get", s, raw, "200")

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
