#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_batch_idempotence_004
# strategy: upsert_idempotence
# endpoint: points+batch
# constraint_ids: qdrant_state_points_batch_001
# source_url: https://qdrant.tech/documentation/manage-data/points/
# doc_version: current (site latest; no version archive)
"""
Attack: upsert idempotence (Strategy 3) at batch granularity x
  qdrant_state_points_batch_001 "operations are executed in order inside
  one batch request". Three faces: (R1) the IDENTICAL batch request
  (upsert 71 + upsert 72) submitted 4 times must leave exactly 2 points
  with stable payloads — batch replay is idempotent per id; (R2) one
  batch containing two upserts of the SAME id (77) with different
  payloads must leave exactly 1 point holding the LATER op's payload
  (sequential last-write-wins inside the batch); (R3) one batch with a
  duplicate delete of id 71 ([delete 71, delete 71]) must decrement the
  count by exactly 1 (in-batch idempotent delete) and must not touch id
  72. Persistence is judged via point readback + exact count.
  [chunk_points+batch coverage: upsert_idempotence x
  qdrant_state_points_batch_001 (identical-batch replay x4 +
  same-id-twice-in-one-batch + duplicated in-batch delete)]
Oracle: R1 after 4 identical submissions exact count == 2 and both ids
  readable with payload {"round":"a"}; R2 exact count == 3 and id 77
  payload == {"try":2} (a second copy / {"try":1} surviving =
  Type4_StateLogicViolation); R3 exact count == 2 with id 71 absent (404)
  and id 72 still present with intact payload (count dropping by 2 or 72
  vanishing = Type4); 200 batch with len(result) != len(operations) =
  Type4 per-op-results violation; 5xx with /healthz alive =
  Type3_RuntimeFailure; transport failure -> liveness re-check before any
  verdict.
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
#   {"path": "points+batch", "method": "POST",
#    "url": "/collections/{collection_name}/points/batch"}
#   {"path": "points+get", "method": "POST",
#    "url": "/collections/{collection_name}/points"}
rt.PATHS["batch_update"] = "/collections/{collection_name}/points/batch"
rt.PATHS["get_points_by_ids"] = "/collections/{collection_name}/points"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if k in ('batch_update', 'get_points_by_ids')]}")

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


def run_batch(tag, coll, ops):
    s, raw = safe_request("POST", "batch_update",
                          path_params={"collection_name": coll},
                          body={"operations": ops},
                          query_params={"wait": "true"})
    print(f"[{tag} batch {len(ops)} ops] status={s} raw={str(raw)[:240]}")
    if s == 0:
        if not liveness(tag):
            ABORT[0] = True
        else:
            DEFECTS.append(f"({tag}) batch transport failure with service "
                           f"alive — Type3_RuntimeFailure")
        return s
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) batch returned {s} with service alive "
                           f"— Type3_RuntimeFailure — raw={str(raw)[:150]}")
        else:
            ABORT[0] = True
        return s
    if s == 200:
        res = result_of(raw)
        if not isinstance(res, list):
            DEFECTS.append(f"({tag}) 200 batch result is not an array — "
                           f"raw={str(raw)[:200]} — Type4_StateLogicViolation")
        elif len(res) != len(ops):
            DEFECTS.append(f"({tag}) 200 batch returned {len(res)} result "
                           f"entries for {len(ops)} operations — "
                           f"Type4_StateLogicViolation")
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
        print(f"SETUP_ERROR: {tag} count result.count missing — raw={str(raw)[:200]}")
        return None
    return cnt


def visible_payloads(tag, coll, ids):
    s, raw = safe_request("POST", "get_points_by_ids",
                          path_params={"collection_name": coll},
                          body={"ids": ids, "with_payload": True})
    print(f"[{tag} get {len(ids)} ids] status={s} raw={str(raw)[:260]}")
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
        print(f"SETUP_ERROR: {tag} batch-get result not a list")
        return None
    out = {}
    for p in res:
        if isinstance(p, dict) and "id" in p:
            out[p["id"]] = p.get("payload") if isinstance(p.get("payload"), dict) else {}
    return out


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spbi4_" + TS + "_"
    C = PFX + "col"
    DIM = 4

    def vec(x):
        return [float(x), 0.5, 0.75, 1.0]

    try:
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"

        # ---- R1: identical batch submitted 4 times -> exactly 2 points ----
        replay = [
            {"upsert": {"points": [
                {"id": 71, "vector": vec(1), "payload": {"round": "a"}},
                {"id": 72, "vector": vec(2), "payload": {"round": "a"}}]}},
        ]
        for attempt in range(4):
            s = run_batch(f"R1-submit-{attempt + 1}", C, replay)
            if s != 200:
                print(f"SETUP_ERROR: R1 submission {attempt + 1} status {s}")
                return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
            cnt = exact_count(f"R1-{attempt + 1}", C)
            if cnt is not None and cnt != 2:
                DEFECTS.append(f"(R1) after {attempt + 1} identical batch "
                               f"submissions exact count {cnt} != 2 — "
                               f"batch replay must be idempotent per id — "
                               f"Type4_StateLogicViolation")
        vis = visible_payloads("R1", C, [71, 72])
        if vis is not None:
            if set(vis.keys()) != {71, 72}:
                DEFECTS.append(f"(R1) visible ids {sorted(vis.keys())} != "
                               f"[71, 72] — Type4_StateLogicViolation")
            for pid in (71, 72):
                if pid in vis and not type_strict_eq(vis[pid], {"round": "a"}):
                    DEFECTS.append(f"(R1) id {pid} payload drifted: "
                                   f"{vis[pid]!r} — Type4_StateLogicViolation")

        # ---- R2: same id twice in ONE batch -> 1 point, later op wins ----
        s = run_batch("R2", C, [
            {"upsert": {"points": [
                {"id": 77, "vector": vec(3), "payload": {"try": 1}}]}},
            {"upsert": {"points": [
                {"id": 77, "vector": vec(4), "payload": {"try": 2}}]}},
        ])
        if s != 200:
            print(f"SETUP_ERROR: R2 status {s}")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        cnt = exact_count("R2", C)
        if cnt is not None and cnt != 3:
            DEFECTS.append(f"(R2) after same-id-twice batch exact count "
                           f"{cnt} != 3 (71,72,77) — duplicate upserts of "
                           f"one id must net exactly one point — "
                           f"Type4_StateLogicViolation")
        vis = visible_payloads("R2", C, [77])
        if vis is not None:
            if set(vis.keys()) != {77}:
                DEFECTS.append(f"(R2) id 77 visible {len(vis)} times "
                               f"(duplicate rows?) — Type4_StateLogicViolation")
            elif not type_strict_eq(vis[77], {"try": 2}):
                DEFECTS.append(f"(R2) id 77 payload {vis[77]!r} != "
                               f"{{'try': 2}} — later op in the batch must "
                               f"win — Type4_StateLogicViolation")

        # ---- R3: duplicated in-batch delete -> exactly -1, surgical ----
        s = run_batch("R3", C, [
            {"delete": {"points": [71]}},
            {"delete": {"points": [71]}},
        ])
        if s != 200:
            print(f"SETUP_ERROR: R3 status {s}")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        cnt = exact_count("R3", C)
        if cnt is not None and cnt != 2:
            DEFECTS.append(f"(R3) after [delete 71, delete 71] exact count "
                           f"{cnt} != 2 — in-batch duplicate delete must "
                           f"decrement exactly once — "
                           f"Type4_StateLogicViolation")
        s, raw = safe_request("GET", "get_point",
                              path_params={"name": C, "point_id": 71})
        print(f"[R3 get deleted 71] status={s} raw={str(raw)[:160]}")
        if s == 200:
            DEFECTS.append(f"(R3) deleted id 71 still retrievable (200) — "
                           f"Type4_StateLogicViolation")
        vis = visible_payloads("R3", C, [72, 77])
        if vis is not None and set(vis.keys()) != {72, 77}:
            DEFECTS.append(f"(R3) delete was not surgical: visible "
                           f"{sorted(vis.keys())} != [72, 77] — "
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
