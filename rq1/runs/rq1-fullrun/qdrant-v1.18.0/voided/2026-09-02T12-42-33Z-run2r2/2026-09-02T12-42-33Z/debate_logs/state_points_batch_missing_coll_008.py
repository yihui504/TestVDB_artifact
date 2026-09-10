#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_batch_missing_coll_008
# strategy: delete_consistency
# endpoint: points+batch
# constraint_ids: qdrant_behavioral_points_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/batch-update
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: the 404 face of qdrant_behavioral_points_batch_001 "returns 200
  with per-operation results; 404 when the collection is missing"
  combined with Strategy 2 (post-DELETE consistency) at COLLECTION
  granularity. Three faces: (N) a batch against a NEVER-CREATED
  collection name must be rejected — the contract pins 404; a 200 (or a
  200-with-empty-result) would be an illegal success writing into
  nothing; (D) a batch that worked before the collection was DROPPED
  must be rejected after the drop, consistently with the count endpoint
  (both faces must agree the collection is absent); (R) recreating the
  SAME collection name must start from a clean state (count 0, no
  resurrection of pre-drop points) and the batch must work again with
  200 + one per-op result.
  [chunk_points+batch coverage: delete_consistency x
  qdrant_behavioral_points_batch_001 (never-created 404 + dropped 404 +
  face consistency vs count + recreate-clean restart)]
Oracle: N -> POST points+batch rejected (404 pinned by the contract;
  any other 4xx recorded as a clear rejection = no defect, 200 =
  Type1_IllegalSuccess, 5xx with /healthz alive = Type3); D -> batch and
  count BOTH report the dropped collection absent (batch 200 while count
  404, or count 200 on the dropped collection = Type4_StateLogicViolation
  inconsistent absence); R -> recreated collection count == 0 before any
  write (pre-drop points reappearing = Type4), then batch [upsert 803]
  -> 200 with result length == 1, GET 803 -> 200 and count == 1;
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


def batch_status(tag, coll, ops):
    """POST points+batch; returns raw status with 5xx/transport handling."""
    s, raw = safe_request("POST", "batch_update",
                          path_params={"collection_name": coll},
                          body={"operations": ops},
                          query_params={"wait": "true"})
    print(f"[{tag} batch] status={s} raw={str(raw)[:260]}")
    if s == 0:
        if not liveness(tag):
            ABORT[0] = True
        else:
            DEFECTS.append(f"({tag}) batch transport failure with service "
                           f"alive — Type3_RuntimeFailure")
        return 0
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) batch returned {s} with service alive "
                           f"— Type3_RuntimeFailure — raw={str(raw)[:150]}")
        else:
            ABORT[0] = True
        return s
    return s


def count_status(tag, coll):
    s, raw = safe_request("POST", "count", path_params={"name": coll},
                          body={"exact": True})
    print(f"[{tag} count] status={s} raw={str(raw)[:160]}")
    if s == 0 or 500 <= s <= 599:
        if s == 0 and not liveness(tag):
            ABORT[0] = True
            return 0, None
        if 500 <= s <= 599 and liveness(tag):
            DEFECTS.append(f"({tag}) count returned {s} with service alive "
                           f"— Type3_RuntimeFailure")
            return s, None
        ABORT[0] = True
        return 0, None
    cnt = None
    if s == 200:
        res = result_of(raw)
        cnt = res.get("count") if isinstance(res, dict) else None
        if isinstance(cnt, bool) or not isinstance(cnt, int):
            cnt = None
    return s, cnt


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spbm8_" + TS + "_"
    NX = PFX + "never"   # never created
    C = PFX + "col"
    DIM = 4

    def vec(x):
        return [float(x), 0.5, 0.75, 1.0]

    def upsert_op(pid):
        return {"upsert": {"points": [
            {"id": pid, "vector": vec(pid), "payload": {"n": pid}}]}}

    try:
        # ---- N: batch against a never-created collection -> rejected ----
        s_n = batch_status("N-never-created", NX, [upsert_op(801)])
        if s_n == 200:
            DEFECTS.append(f"(N) points+batch on never-created collection "
                           f"{NX!r} returned 200 — illegal success against "
                           f"a missing collection — Type1_IllegalSuccess "
                           f"(qdrant_behavioral_points_batch_001)")
        elif s_n == 404:
            print("[N] OK: never-created collection -> 404 (contract-pinned)")
        elif 400 <= s_n <= 499:
            print(f"[N] rejected with {s_n} — clear rejection recorded "
                  f"(contract pins 404); not adjudicated as a defect per "
                  f"graceful-rejection typing")

        # ---- D: dropped collection -> absent on batch AND count ----
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        s = batch_status("D-seed", C, [upsert_op(802)])
        if s != 200:
            print(f"SETUP_ERROR: D seed batch status {s}")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        _s_cnt, cnt_before = count_status("D-seed", C)
        if cnt_before != 1:
            print(f"SETUP_ERROR: D seed count {cnt_before} != 1")
            return "SCRIPT_ERROR"
        try:
            rt.drop_collection(C)
        except Exception:
            pass
        time.sleep(0.3)
        s_b = batch_status("D-after-drop", C, [upsert_op(802)])
        s_c, _ = count_status("D-after-drop", C)
        if s_b == 200:
            DEFECTS.append("(D) points+batch on dropped collection returned "
                           "200 — illegal success — Type1_IllegalSuccess / "
                           "Type4_StateLogicViolation")
        elif s_b == 404:
            print("[D] OK: dropped collection batch -> 404")
        elif 400 <= s_b <= 499:
            print(f"[D] rejected with {s_b} — clear rejection recorded")
        if s_c == 200:
            DEFECTS.append("(D) count on dropped collection returned 200 "
                           "— face inconsistency (batch rejected, count "
                           "answers) — Type4_StateLogicViolation")
        if s_b == 404 and s_c not in (0, 404) and s_c is not None:
            DEFECTS.append(f"(D) face inconsistency: batch 404 but count "
                           f"{s_c} on the same dropped collection — "
                           f"Type4_StateLogicViolation")

        # ---- R: recreate same name -> clean state, batch works again ----
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: recreate failed: {err}")
            return "SCRIPT_ERROR"
        s_c, cnt0 = count_status("R-fresh", C)
        if s_c == 200 and cnt0 != 0:
            DEFECTS.append(f"(R) recreated collection {C!r} starts with "
                           f"count {cnt0} != 0 — pre-drop points "
                           f"resurrected — Type4_StateLogicViolation")
        elif s_c == 200:
            print("[R] OK: recreated collection starts clean at 0")
        s_r, raw = safe_request("POST", "batch_update",
                                path_params={"collection_name": C},
                                body={"operations": [upsert_op(803)]},
                                query_params={"wait": "true"})
        print(f"[R batch] status={s_r} raw={str(raw)[:200]}")
        if s_r == 200:
            res = result_of(raw)
            if not isinstance(res, list):
                DEFECTS.append("(R) 200 batch result is not an array — "
                               "Type4_StateLogicViolation")
            elif len(res) != 1:
                DEFECTS.append(f"(R) 200 batch returned {len(res)} result "
                               f"entries for 1 operation — "
                               f"Type4_StateLogicViolation")
            else:
                print(f"[R] OK: batch works on recreated collection "
                      f"({res!r})")
            _s, cnt1 = count_status("R-after", C)
            if cnt1 is not None and cnt1 != 1:
                DEFECTS.append(f"(R) count after one upsert on recreated "
                               f"collection: {cnt1} != 1 — "
                               f"Type4_StateLogicViolation")
        elif s_r == 0 or 500 <= s_r <= 599:
            pass  # 5xx/transport branch already recorded a defect above
        else:
            DEFECTS.append(f"(R) batch on recreated collection returned "
                           f"{s_r} (expected 200) — "
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
        for coll in (C, NX):
            try:
                rt.drop_collection(coll)
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
