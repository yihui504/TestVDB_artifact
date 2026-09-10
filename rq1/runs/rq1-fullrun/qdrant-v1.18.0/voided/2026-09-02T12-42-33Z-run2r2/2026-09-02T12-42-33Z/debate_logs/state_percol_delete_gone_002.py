#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_percol_delete_gone_002
# strategy: delete_consistency
# endpoint: per_collection
# constraint_ids: qdrant_inv_delete_gone_001
# source_url: https://qdrant.tech/documentation/manage-data/collections/
# doc_version: current (site latest; no version archive)
"""
Attack: delete_consistency (Strategy 2: post-DELETE consistency, sequence
  Pattern D state-jump extension) x qdrant_inv_delete_gone_001 "after a
  successful delete the collection must not exist" whose assertion pins
  THREE gone faces: absent from the list, details access returns 404,
  exists reports result.exists=false. This script deletes a DATA-BEARING
  collection and walks every access face (G9 cross-face consistency):
  (A) create + upsert 3 points wait=true + count=3 (positive pre-state);
  (B) DELETE /collections/{name} -> 200;
  (C) gone faces: list must NOT contain the name; describe 404; exists
      200 with result.exists=false; count/scroll/upsert/get_point against
      the deleted name -> 404 each. A 200 on any mutation/read face =
      ghost collection (Type4); a 5xx with /healthz alive = Type3;
  (D) state jump: recreate the SAME name -> describe 200, exists=true,
      exact count=0 — no zombie data resurrection from the pre-delete
      era (data deleted with the collection must stay deleted).
  [chunk_per_collection coverage: delete_consistency x
  qdrant_inv_delete_gone_001 (all gone faces + recreate state jump)]
Oracle: DELETE -> 200; afterwards list excludes the name, describe ->
  404, exists -> 200 with result.exists=false, and count/scroll/upsert/
  get_point each -> 404 (a 200 on any gone face = Type4_StateLogicViolation
  ghost collection; 5xx with /healthz alive = Type3_RuntimeFailure);
  after recreate of the same name: describe 200, exists=true, exact
  count=0 — count>0 after recreate = Type4_StateLogicViolation (zombie
  data resurrection).
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
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if k == 'exists_collection']}")

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


def face(tag, status, raw, expect):
    """expect: '404' (gone face) / '200' (must-work face). Returns ok/fail."""
    if status == 0:
        if not liveness(tag):
            ABORT[0] = True
        else:
            DEFECTS.append(f"({tag}) transport failure with service alive — "
                           f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
        return "fail"
    if 500 <= status <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) returned {status} with service alive — "
                           f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
        else:
            ABORT[0] = True
        return "fail"
    if expect == "404" and status != 404:
        DEFECTS.append(f"({tag}) expected 404 on the deleted collection, "
                       f"got {status} — Type4_StateLogicViolation (ghost "
                       f"collection) — raw={str(raw)[:150]}")
        return "fail"
    if expect == "200" and status != 200:
        DEFECTS.append(f"({tag}) expected 200, got {status} — "
                       f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
        return "fail"
    return "ok"


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spdg2_" + TS + "_"
    C = PFX + "col"
    DIM = 4

    try:
        # ---- (A positive pre-state: data-bearing collection) ----
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        pts = [{"id": i, "vector": [float(i), 1.0, 0.5, 2.0],
                "payload": {"n": i}} for i in range(3)]
        s, raw = safe_request("PUT", "upsert_points",
                              path_params={"name": C}, body={"points": pts},
                              query_params={"wait": "true"})
        print(f"[A upsert 3] status={s} raw={raw[:150]}")
        if s != 200:
            print("SETUP_ERROR: pre-delete upsert failed")
            return "SCRIPT_ERROR"
        s, raw = safe_request("POST", "count", path_params={"name": C},
                              body={"exact": True})
        cnt = result_of(raw)
        cnt = cnt.get("count") if isinstance(cnt, dict) else None
        print(f"[A count] status={s} count={cnt}")
        if s != 200 or cnt != 3:
            print("SETUP_ERROR: pre-delete count != 3")
            return "SCRIPT_ERROR"

        # ---- (B delete) ----
        s, raw = safe_request("DELETE", "drop_collection",
                              path_params={"name": C})
        print(f"[B delete] status={s} raw={raw[:160]}")
        if s == 0 or 500 <= s <= 599 or s != 200:
            if s == 0 or 500 <= s <= 599:
                liveness("B delete")
            print(f"SETUP_ERROR: delete returned {s}")
            return "SCRIPT_ERROR"

        # ---- (C gone faces) ----
        s, raw = safe_request("GET", "list_collections")
        print(f"[C list] status={s} raw={raw[:200]}")
        if face("C list", s, raw, "200") == "ok":
            res = result_of(raw)
            cols = res.get("collections") if isinstance(res, dict) else None
            names = [c.get("name") for c in cols
                     if isinstance(c, dict)] if isinstance(cols, list) else []
            if C in names:
                DEFECTS.append("(C list) deleted collection still present in "
                               f"collections list — Type4_StateLogicViolation")
            else:
                print("[C list] OK: name absent")

        s, raw = safe_request("GET", "describe_collection",
                              path_params={"name": C})
        print(f"[C describe] status={s} raw={raw[:160]}")
        face("C describe", s, raw, "404")

        s, raw = safe_request("GET", "exists_collection",
                              path_params={"collection_name": C})
        print(f"[C exists] status={s} raw={raw[:160]}")
        if face("C exists", s, raw, "200") == "ok":
            res = result_of(raw)
            ex = res.get("exists") if isinstance(res, dict) else None
            if ex is not False:
                DEFECTS.append("(C exists) after delete result.exists="
                               f"{ex!r} (expected false) — "
                               f"Type4_StateLogicViolation")
            else:
                print("[C exists] OK: exists=false")

        s, raw = safe_request("POST", "count", path_params={"name": C},
                              body={"exact": True})
        print(f"[C count] status={s} raw={raw[:160]}")
        face("C count", s, raw, "404")

        s, raw = safe_request("POST", "scroll", path_params={"name": C},
                              body={"limit": 10})
        print(f"[C scroll] status={s} raw={raw[:160]}")
        face("C scroll", s, raw, "404")

        s, raw = safe_request("PUT", "upsert_points",
                              path_params={"name": C},
                              body={"points": [{"id": 99,
                                                "vector": [1.0] * DIM}]},
                              query_params={"wait": "true"})
        print(f"[C upsert] status={s} raw={raw[:160]}")
        face("C upsert", s, raw, "404")

        s, raw = safe_request("GET", "get_point",
                              path_params={"name": C, "point_id": 0})
        print(f"[C get_point] status={s} raw={raw[:160]}")
        face("C get_point", s, raw, "404")

        # ---- (D state jump: recreate same name) ----
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: recreate failed: {err}")
            return "SCRIPT_ERROR"
        s, raw = safe_request("GET", "exists_collection",
                              path_params={"collection_name": C})
        print(f"[D exists] status={s} raw={raw[:160]}")
        if face("D exists", s, raw, "200") == "ok":
            res = result_of(raw)
            ex = res.get("exists") if isinstance(res, dict) else None
            if ex is not True:
                DEFECTS.append("(D exists) after recreate result.exists="
                               f"{ex!r} (expected true) — "
                               f"Type4_StateLogicViolation")
        s, raw = safe_request("POST", "count", path_params={"name": C},
                              body={"exact": True})
        print(f"[D count] status={s} raw={raw[:160]}")
        if face("D count", s, raw, "200") == "ok":
            res = result_of(raw)
            cnt = res.get("count") if isinstance(res, dict) else None
            if cnt != 0:
                DEFECTS.append("(D count) recreated collection count="
                               f"{cnt!r} (expected 0 — zombie data "
                               f"resurrection) — Type4_StateLogicViolation")
            else:
                print("[D count] OK: count=0 after recreate")

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
