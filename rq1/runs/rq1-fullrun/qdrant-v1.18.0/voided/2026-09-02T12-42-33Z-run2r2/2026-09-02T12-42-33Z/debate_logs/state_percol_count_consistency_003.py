#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_percol_count_consistency_003
# strategy: count_consistency
# endpoint: per_collection
# constraint_ids: qdrant_inv_count_consistency_001
# source_url: https://qdrant.tech/documentation/manage-data/points/
# doc_version: current (site latest; no version archive)
"""
Attack: count_consistency (Strategy 1: CRUD-then-COUNT) + upsert_idempotence
  (Strategy 3, folded in — same-id re-upsert must not grow the count) x
  qdrant_inv_count_consistency_001 "after inserting N points (wait=true)
  the exact count reflects N" whose assertion covers BOTH the whole
  collection AND the matching filter. Sequence on one collection:
  (T1 insert face) upsert 5 distinct ids wait=true -> exact count == 5;
  (T2 idempotence face) re-upsert the SAME 5 ids with different vectors
      wait=true -> exact count STILL 5 (id-addressed upsert replaces, it
      must not append);
  (T3 growth face) upsert 3 new ids wait=true -> exact count == 8;
  (T4 filtered face) 3 of the 8 points carry payload city="red", 5 carry
      city="blue": exact count with filter must match city=red == 3 and
      city=blue == 5, and the two filtered counts must SUM to the whole
      collection count (partition consistency);
  (T5 delete face) delete 3 ids wait=true -> exact count == 5 and the
      filtered counts re-adjust exactly (the deleted ids were all
      city="blue", so blue drops to 2, red stays 3, sum == 5).
  Every count uses exact=true and reads result.count from the envelope;
  each face prints the raw response for adjudication.
  [chunk_per_collection coverage: count_consistency + upsert_idempotence x
  qdrant_inv_count_consistency_001 (insert/idempotence/growth/filtered/
  delete faces)]
Oracle: T1 -> count 5; T2 -> count stays 5 (count==10 after re-upserting
  existing ids = Type4_StateLogicViolation duplicate-append); T3 -> 8;
  T4 -> filter match city=red gives 3, city=blue gives 5, and
  red+blue == whole-collection count (a filtered count that disagrees
  with the payload partition = Type4_StateLogicViolation); T5 -> 5 with
  blue==2, red==3 (post-delete count drift = Type4). Any count face 5xx
  with /healthz alive = Type3_RuntimeFailure; transport failure ->
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


def upsert(tag, coll, points):
    s, raw = safe_request("PUT", "upsert_points",
                          path_params={"name": coll},
                          body={"points": points},
                          query_params={"wait": "true"})
    print(f"[{tag} upsert x{len(points)}] status={s} raw={raw[:150]}")
    if s == 0:
        if not liveness(tag):
            ABORT[0] = True
            return False
        DEFECTS.append(f"({tag}) upsert transport failure with service "
                       f"alive — Type3_RuntimeFailure — raw={str(raw)[:150]}")
        return False
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) upsert returned {s} with service alive "
                           f"— Type3_RuntimeFailure — raw={str(raw)[:150]}")
        else:
            ABORT[0] = True
        return False
    if s != 200:
        print(f"SETUP_ERROR: {tag} upsert returned {s}")
        return False
    return True


def exact_count(tag, coll, flt=None):
    """exact=true count (whole collection or filtered). None on abort."""
    body = {"exact": True}
    if flt is not None:
        body["filter"] = flt
    s, raw = safe_request("POST", "count", path_params={"name": coll},
                          body=body)
    print(f"[{tag} count{' filtered' if flt else ''}] status={s} raw={raw[:160]}")
    if s == 0:
        if not liveness(tag):
            ABORT[0] = True
        else:
            DEFECTS.append(f"({tag}) count transport failure with service "
                           f"alive — Type3_RuntimeFailure")
        return None
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) count returned {s} with service alive "
                           f"— Type3_RuntimeFailure — raw={str(raw)[:150]}")
        else:
            ABORT[0] = True
        return None
    if s != 200:
        print(f"SETUP_ERROR: {tag} count returned {s}")
        return None
    try:
        res = json.loads(raw).get("result")
        cnt = res.get("count") if isinstance(res, dict) else None
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        cnt = None
    if isinstance(cnt, bool) or not isinstance(cnt, int):
        print(f"SETUP_ERROR: {tag} count result.count missing — raw={raw[:200]}")
        return None
    return cnt


def check_count(tag, got, expected):
    if got is None:
        return False
    if got != expected:
        DEFECTS.append(f"({tag}) exact count {got} != expected {expected} — "
                       f"Type4_StateLogicViolation "
                       f"(qdrant_inv_count_consistency_001)")
        return False
    print(f"[{tag}] OK: exact count == {expected}")
    return True


MATCH_RED = {"must": [{"key": "city", "match": {"value": "red"}}]}
MATCH_BLUE = {"must": [{"key": "city", "match": {"value": "blue"}}]}


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sccs3_" + TS + "_"
    C = PFX + "col"
    DIM = 4

    def vec(i):
        return [float(i) + 0.1, 0.2, 0.3, 0.4]

    try:
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"

        # ---- (T1 insert face) ----
        t1 = [{"id": i, "vector": vec(i), "payload": {"n": i}} for i in range(5)]
        if not upsert("T1", C, t1):
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        check_count("T1", exact_count("T1", C), 5)

        # ---- (T2 idempotence face: same ids, new vectors) ----
        t2 = [{"id": i, "vector": vec(100 + i), "payload": {"n": 100 + i}}
              for i in range(5)]
        if not upsert("T2", C, t2):
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        check_count("T2", exact_count("T2", C), 5)

        # ---- (T3 growth face) ----
        t3 = [{"id": 5 + j, "vector": vec(5 + j),
               "payload": {"n": 5 + j, "city": "blue"}} for j in range(3)]
        if not upsert("T3", C, t3):
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        check_count("T3", exact_count("T3", C), 8)

        # ---- (T4 filtered face) ----
        t4 = [{"id": i, "vector": vec(200 + i),
               "payload": {"n": 200 + i, "city": "red" if i < 3 else "blue"}}
              for i in range(5)]
        if not upsert("T4", C, t4):
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        whole = exact_count("T4", C)
        red = exact_count("T4 red", C, MATCH_RED)
        blue = exact_count("T4 blue", C, MATCH_BLUE)
        check_count("T4 whole", whole, 8)
        check_count("T4 red", red, 3)
        check_count("T4 blue", blue, 5)
        if None not in (whole, red, blue) and red + blue != whole:
            DEFECTS.append(f"(T4 partition) filtered counts red={red} + "
                           f"blue={blue} != whole={whole} — the exact count "
                           f"must reflect the matching filter — "
                           f"Type4_StateLogicViolation")

        # ---- (T5 delete face: remove the 3 city=blue-only ids 5,6,7) ----
        s, raw = safe_request("POST", "delete_points",
                              path_params={"name": C},
                              body={"points": [5, 6, 7]},
                              query_params={"wait": "true"})
        print(f"[T5 delete 5,6,7] status={s} raw={raw[:150]}")
        if s == 0 or 500 <= s <= 599:
            liveness("T5 delete")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if s != 200:
            print(f"SETUP_ERROR: T5 delete returned {s}")
            return "SCRIPT_ERROR"
        check_count("T5", exact_count("T5", C), 5)
        red5 = exact_count("T5 red", C, MATCH_RED)
        blue5 = exact_count("T5 blue", C, MATCH_BLUE)
        check_count("T5 red", red5, 3)
        check_count("T5 blue", blue5, 2)
        if None not in (red5, blue5) and red5 + blue5 != 5:
            DEFECTS.append(f"(T5 partition) filtered counts red={red5} + "
                           f"blue={blue5} != whole=5 after delete — "
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
