#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_percol_point_delete_gone_005
# strategy: delete_consistency
# endpoint: per_collection
# constraint_ids: qdrant_inv_point_delete_gone_001
# source_url: https://qdrant.tech/documentation/manage-data/points/
# doc_version: current (site latest; no version archive)
"""
Attack: delete_consistency (Strategy 2 at POINT granularity) x
  qdrant_inv_point_delete_gone_001 "after a successful point delete
  (wait=true) the point is not retrievable" whose assertion pins THREE
  retrieval faces: deleted ids absent from batch-get results, absent
  from filtered scrolls, and a single get of a deleted id returns 404.
  Sequence: (A) upsert 6 points ids 0..5 with typed payloads
  {"n": i, "parity": even/odd}; count == 6 (positive pre-state);
  (B) delete points {1,3,5} wait=true -> 200; count == 3;
  (C1) batch-get all 6 ids: result contains EXACTLY the survivor ids
      {0,2,4}, each payload deep-equal (type-strict) to what was sent;
  (C2) filtered scroll must has_id [1,3,5] -> 200 with points == []
      (deleted ids must not leak through a filtered read);
  (C3) single GET point 1 -> 404; single GET point 0 -> 200 (the
      survivor keeps working — the delete must be surgical);
  (D) resurrection face: re-upsert id 1 with a NEW payload -> single
      GET 200 with exactly the new payload, count == 4 (a deleted id
      address is reusable, and the count agrees);
  (E) by-design note: deleting an already-deleted id returns 200
      (idempotent REST delete, declared by-design in the threat model) —
      printed, NOT adjudicated as a defect.
  [chunk_per_collection coverage: delete_consistency x
  qdrant_inv_point_delete_gone_001 (batch-get absence + filtered-scroll
  absence + single 404 + survivor integrity + reinsert resurrection)]
Oracle: B -> 200 and count 6 -> 3 exactly; C1 -> batch-get returns
  exactly ids {0,2,4} with type-strict payload equality (a deleted id
  appearing, or a survivor missing/payload-corrupted =
  Type4_StateLogicViolation); C2 -> 200 with empty points (deleted ids
  in the filtered scroll = Type4); C3 -> GET deleted id 404 (200 =
  Type4 zombie point; 5xx with /healthz alive = Type3), GET survivor
  200; D -> reinserted id GET 200 with the new payload and count == 4;
  transport failures -> liveness re-check before any verdict.
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

# points+get (batch) is not in the runtime PATHS whitelist — register
# VERBATIM from raw_knowledge api_endpoints[].url:
#   {"path": "points+get", "method": "POST",
#    "url": "/collections/{collection_name}/points/get"}
rt.PATHS["get_points"] = "/collections/{collection_name}/points/get"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if k == 'get_points']}")

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


def type_strict_eq(a, b):
    """Deep equality with STRICT JSON type identity (bool checked before
    int; int vs float distinct per contract data_types payload classes)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return type(a) is type(b) and a == b
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return (set(a.keys()) == set(b.keys())
                and all(type_strict_eq(a[k], b[k]) for k in a))
    if isinstance(a, list):
        return (len(a) == len(b)
                and all(type_strict_eq(x, y) for x, y in zip(a, b)))
    return a == b


def exact_count(tag, coll):
    s, raw = safe_request("POST", "count", path_params={"name": coll},
                          body={"exact": True})
    print(f"[{tag} count] status={s} raw={str(raw)[:160]}")
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
    res = result_of(raw)
    cnt = res.get("count") if isinstance(res, dict) else None
    if isinstance(cnt, bool) or not isinstance(cnt, int):
        print(f"SETUP_ERROR: {tag} count result.count missing — raw={str(raw)[:200]}")
        return None
    return cnt


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spdl5_" + TS + "_"
    C = PFX + "col"
    DIM = 4

    def payload_of(i):
        return {"n": i, "parity": "odd" if i % 2 else "even"}

    def vec(i):
        return [float(i) + 0.25, 0.5, 0.75, 1.0]

    try:
        # ---- (A positive pre-state) ----
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        pts = [{"id": i, "vector": vec(i), "payload": payload_of(i)}
               for i in range(6)]
        s, raw = safe_request("PUT", "upsert_points",
                              path_params={"name": C}, body={"points": pts},
                              query_params={"wait": "true"})
        print(f"[A upsert 6] status={s} raw={raw[:150]}")
        if s != 200:
            print("SETUP_ERROR: A upsert failed")
            return "SCRIPT_ERROR"
        if exact_count("A", C) != 6:
            print("SETUP_ERROR: A count != 6")
            return "SCRIPT_ERROR"

        # ---- (B delete points 1,3,5) ----
        s, raw = safe_request("POST", "delete_points",
                              path_params={"name": C},
                              body={"points": [1, 3, 5]},
                              query_params={"wait": "true"})
        print(f"[B delete 1,3,5] status={s} raw={raw[:150]}")
        if s == 0 or 500 <= s <= 599:
            liveness("B delete")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if s != 200:
            print(f"SETUP_ERROR: B delete returned {s}")
            return "SCRIPT_ERROR"
        got = exact_count("B", C)
        if got is not None and got != 3:
            DEFECTS.append(f"(B count) exact count {got} != 3 after "
                           f"deleting 3 of 6 points — "
                           f"Type4_StateLogicViolation")

        # ---- (C1 batch-get absence) ----
        s, raw = safe_request("POST", "get_points",
                              path_params={"collection_name": C},
                              body={"ids": list(range(6)),
                                    "with_payload": True})
        print(f"[C1 batch get all 6] status={s} raw={raw[:240]}")
        if s == 0:
            liveness("C1")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if 500 <= s <= 599:
            if liveness("C1"):
                DEFECTS.append(f"(C1) batch get returned {s} with service "
                               f"alive — Type3_RuntimeFailure")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if s != 200:
            print(f"SETUP_ERROR: C1 batch get returned {s}")
            return "SCRIPT_ERROR"
        res = result_of(raw)
        got_list = res if isinstance(res, list) else None
        if not isinstance(got_list, list):
            print(f"SETUP_ERROR: C1 result is not a list — raw={raw[:200]}")
            return "SCRIPT_ERROR"
        got_ids = sorted(p.get("id") for p in got_list
                         if isinstance(p, dict))
        if got_ids != [0, 2, 4]:
            DEFECTS.append(f"(C1) batch-get after delete returned ids "
                           f"{got_ids} (expected exactly [0, 2, 4]) — "
                           f"Type4_StateLogicViolation "
                           f"(qdrant_inv_point_delete_gone_001)")
        else:
            print("[C1] OK: exactly survivors [0, 2, 4]")
            for p in got_list:
                i = p.get("id")
                pl = p.get("payload")
                pl = pl if isinstance(pl, dict) else {}
                if not type_strict_eq(pl, payload_of(i)):
                    DEFECTS.append(f"(C1) survivor {i} payload drifted: "
                                   f"{pl!r} != {payload_of(i)!r} — "
                                   f"Type4_StateLogicViolation")

        # ---- (C2 filtered scroll absence) ----
        s, raw = safe_request("POST", "scroll", path_params={"name": C},
                              body={"limit": 10, "with_payload": True,
                                    "filter": {"must": [{"has_id": [1, 3, 5]}]}})
        print(f"[C2 filtered scroll] status={s} raw={raw[:200]}")
        if s == 0:
            liveness("C2")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if 500 <= s <= 599:
            if liveness("C2"):
                DEFECTS.append(f"(C2) filtered scroll returned {s} with "
                               f"service alive — Type3_RuntimeFailure")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if s != 200:
            print(f"SETUP_ERROR: C2 scroll returned {s}")
            return "SCRIPT_ERROR"
        res = result_of(raw)
        spts = res.get("points") if isinstance(res, dict) else None
        if not isinstance(spts, list):
            print(f"SETUP_ERROR: C2 result.points missing — raw={raw[:200]}")
            return "SCRIPT_ERROR"
        leaked = [p.get("id") for p in spts if isinstance(p, dict)]
        if leaked:
            DEFECTS.append(f"(C2) filtered scroll on deleted ids returned "
                           f"{leaked} — Type4_StateLogicViolation")
        else:
            print("[C2] OK: deleted ids absent from filtered scroll")

        # ---- (C3 single-get faces) ----
        s, raw = safe_request("GET", "get_point",
                              path_params={"name": C, "point_id": 1})
        print(f"[C3 get deleted 1] status={s} raw={raw[:160]}")
        if s != 404:
            if s == 0:
                liveness("C3 deleted")
            elif 500 <= s <= 599:
                if liveness("C3 deleted"):
                    DEFECTS.append(f"(C3) GET deleted point returned {s} "
                                   f"with service alive — "
                                   f"Type3_RuntimeFailure")
            else:
                DEFECTS.append(f"(C3) GET deleted point 1 returned {s} "
                               f"(expected 404) — zombie point — "
                               f"Type4_StateLogicViolation")
        else:
            print("[C3] OK: deleted point 1 -> 404")
        s, raw = safe_request("GET", "get_point",
                              path_params={"name": C, "point_id": 0})
        print(f"[C3 get survivor 0] status={s} raw={raw[:160]}")
        if s != 200:
            if s == 0:
                liveness("C3 survivor")
            elif 500 <= s <= 599 and liveness("C3 survivor"):
                DEFECTS.append(f"(C3) GET survivor returned {s} with "
                               f"service alive — Type3_RuntimeFailure")
            else:
                DEFECTS.append(f"(C3) survivor 0 not retrievable ({s}) — "
                               f"delete must be surgical — "
                               f"Type4_StateLogicViolation")

        # ---- (D resurrection face) ----
        D_NEW = {"n": 1001, "parity": "reborn"}
        s, raw = safe_request("PUT", "upsert_points",
                              path_params={"name": C},
                              body={"points": [{"id": 1, "vector": vec(1),
                                                "payload": D_NEW}]},
                              query_params={"wait": "true"})
        print(f"[D re-upsert 1] status={s} raw={raw[:150]}")
        if s != 200:
            print(f"SETUP_ERROR: D re-upsert returned {s}")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        s, raw = safe_request("GET", "get_point",
                              path_params={"name": C, "point_id": 1})
        print(f"[D get 1] status={s} raw={raw[:200]}")
        if s == 200:
            res = result_of(raw)
            pl = res.get("payload") if isinstance(res, dict) else None
            pl = pl if isinstance(pl, dict) else {}
            if not type_strict_eq(pl, D_NEW):
                DEFECTS.append(f"(D) reinserted point 1 payload {pl!r} != "
                               f"{D_NEW!r} — Type4_StateLogicViolation")
            else:
                print("[D] OK: reinserted point 1 retrievable with new payload")
        else:
            DEFECTS.append(f"(D) reinserted point 1 GET returned {s} "
                           f"(expected 200) — Type4_StateLogicViolation")
        got = exact_count("D", C)
        if got is not None and got != 4:
            DEFECTS.append(f"(D count) exact count {got} != 4 after "
                           f"resurrecting 1 of 3 survivors — "
                           f"Type4_StateLogicViolation")

        # ---- (E by-design: idempotent re-delete) ----
        s, raw = safe_request("POST", "delete_points",
                              path_params={"name": C}, body={"points": [1]},
                              query_params={"wait": "true"})
        print(f"[E re-delete 1] status={s} raw={raw[:150]}")
        print("SKIPPED-by-design: idempotent DELETE of an existing point "
              "returning non-4xx is declared by-design per threat_model "
              "(RESTful idempotent delete) — not adjudicated")
        if s == 200:
            got = exact_count("E", C)
            if got is not None and got != 3:
                DEFECTS.append(f"(E count) exact count {got} != 3 after "
                               f"idempotent re-delete — "
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
