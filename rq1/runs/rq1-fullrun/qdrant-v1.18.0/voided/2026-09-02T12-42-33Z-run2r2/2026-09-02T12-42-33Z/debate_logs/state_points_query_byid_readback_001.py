#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_query_byid_readback_001
# strategy: state_readback_after_overwrite
# endpoint: points+query
# constraint_ids: qdrant_state_points_query_001
# source_url: https://qdrant.tech/documentation/search/search/
# doc_version: current (site latest; no version archive)
"""
Attack: by-id query stored-vector readback after overwrite (Strategy 1/3
  flavor: CRUD-then-readback + upsert last-write-wins) x
  qdrant_state_points_query_001 "by-id lookup (query = point id) fetches
  the stored vector of that point". Seed 5 points: id 100 with V1=+x axis,
  201/202 at 3/6 degrees from +x, 301/302 at 3/6 degrees from +y.
  (B) baseline: query {"query": 100} must rank 201 first (nearest to the
  STORED V1). (O) overwrite id 100 with V2=+y axis (wait=true) — count must
  stay 5 (id reuse adds no point). (R) query {"query": 100} again must now
  rank 301 first: the by-id lookup must read the CURRENT stored vector
  (last-write-wins), never a stale pre-overwrite vector. Cross-check the
  stored state via POST batch-get with_vector=true: id 100's vector must
  match V2 (readback-vs-baseline comparison, no absolute-score asserts —
  Cosine oracle discipline). Mutation-point justification (G6): overwrite
  is the mutation that most directly breaks a by-id lookup that caches or
  pins the vector at first sight; duplicate-id upsert is the only write
  that changes the hidden state a by-id query depends on while leaving
  every other observable (count, id set) unchanged.
  [chunk_points+query coverage: state_readback_after_overwrite x
  qdrant_state_points_query_001 (baseline by-id ranking + overwrite flip
  + count-idempotence arithmetic + with_vector readback cross-check)]
Oracle: (B) by-id query returns HTTP 200 and its top result (excluding id
  100 itself) is id 201; (O) overwrite returns 200 and exact count stays 5
  (count 6 = duplicate-id leak, Type4_StateLogicViolation); (R) second
  by-id query returns 200 and its top result (excluding id 100) is id 301
  — top still 201 means the by-id lookup served the stale pre-overwrite
  vector (Type4_StateLogicViolation); batch-get vector of id 100 must be
  cosine-close (>=0.999) to V2 and not to V1; 5xx with /healthz alive =
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

# URLs used VERBATIM from raw_knowledge api_endpoints[]:
#   {"method": "POST", "url": "/collections/{collection_name}/points"} -> POST batch-get face
# runtime PATHS already carries query/upsert_points/count/get_point verbatim; only the
# POST batch-get face needs registration (runtime has no POST key on that URL).
rt.PATHS["get_points_by_ids"] = "/collections/{collection_name}/points"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if k in ('query', 'get_points_by_ids', 'upsert_points', 'count')]}")

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


def handle_transport(tag, status, raw):
    """0-transport / 5xx classification with mandatory liveness re-check."""
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


def result_of(raw):
    try:
        return json.loads(raw).get("result")
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        return None


def upsert(coll, points):
    s, raw = safe_request("PUT", "upsert_points",
                          path_params={"name": coll},
                          body={"points": points},
                          query_params={"wait": "true"})
    print(f"[upsert {len(points)} pts] status={s} raw={str(raw)[:160]}")
    if handle_transport("upsert", s, raw):
        return False
    return s == 200


def exact_count(tag, coll):
    s, raw = safe_request("POST", "count", path_params={"name": coll},
                          body={"exact": True})
    print(f"[{tag} count] status={s} raw={str(raw)[:160]}")
    if handle_transport(f"{tag} count", s, raw):
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


def byid_query(tag, coll, pid, limit=3):
    """POST /collections/{c}/points/query with bare point id (by-id lookup).
    Returns (status, ranked_ids) where ranked_ids excludes the queried id."""
    body = {"query": pid, "limit": limit}
    s, raw = safe_request("POST", "query", path_params={"name": coll}, body=body)
    print(f"[{tag} by-id query {pid}] status={s} raw={str(raw)[:240]}")
    if handle_transport(tag, s, raw):
        return s, None
    if s != 200:
        return s, None
    res = result_of(raw)
    pts = res.get("points") if isinstance(res, dict) else None
    if not isinstance(pts, list):
        DEFECTS.append(f"({tag}) 200 but result.points is not an array "
                       f"(contract response_shape: result.points array) — "
                       f"raw={str(raw)[:150]}")
        return s, None
    ids = [p.get("id") for p in pts if isinstance(p, dict)]
    ids_wo_self = [i for i in ids if i != pid]
    return s, ids_wo_self


def batch_get_vector(tag, coll, pid):
    s, raw = safe_request("POST", "get_points_by_ids",
                          path_params={"collection_name": coll},
                          body={"ids": [pid], "with_vector": True})
    print(f"[{tag} batch-get {pid} with_vector] status={s} raw={str(raw)[:240]}")
    if handle_transport(f"{tag} batch-get", s, raw):
        return None
    if s != 200:
        return None
    res = result_of(raw)
    if not isinstance(res, list) or not res:
        return None
    return res[0].get("vector") if isinstance(res[0], dict) else None


def cosine(a, b):
    if not isinstance(a, list) or not isinstance(b, list) or len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return None
    return dot / (na * nb)


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spq1_" + TS + "_"
    C = PFX + "col"
    DIM = 4

    V1 = [1.0, 0.0, 0.0, 0.0]                 # +x axis (initial stored vector of id 100)
    V2 = [0.0, 1.0, 0.0, 0.0]                 # +y axis (post-overwrite stored vector)
    NEAR_X1 = [0.99863, 0.05234, 0.0, 0.0]    # id 201, ~3deg from +x
    NEAR_X2 = [0.99452, 0.10453, 0.0, 0.0]    # id 202, ~6deg from +x
    NEAR_Y1 = [0.05234, 0.99863, 0.0, 0.0]    # id 301, ~3deg from +y
    NEAR_Y2 = [0.10453, 0.99452, 0.0, 0.0]    # id 302, ~6deg from +y

    seed = [
        {"id": 100, "vector": V1},
        {"id": 201, "vector": NEAR_X1},
        {"id": 202, "vector": NEAR_X2},
        {"id": 301, "vector": NEAR_Y1},
        {"id": 302, "vector": NEAR_Y2},
    ]

    try:
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        if not upsert(C, seed):
            print("SETUP_ERROR: seed upsert failed")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        cnt = exact_count("seed", C)
        if cnt != 5:
            print(f"SETUP_ERROR: seed count {cnt} != 5")
            return "SCRIPT_ERROR"

        # ---- B: baseline by-id ranking (uses the stored V1) ----
        sB, ranked_b = byid_query("B-baseline", C, 100, limit=4)
        if sB != 200 or ranked_b is None:
            print("SETUP_ERROR: baseline by-id query not 200")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if not ranked_b:
            DEFECTS.append("(B) baseline by-id query returned no other points "
                           "— Type4_StateLogicViolation")
        elif ranked_b[0] != 201:
            DEFECTS.append(f"(B) baseline by-id top neighbour {ranked_b[0]} != 201 "
                           f"(stored vector is V1=+x; 201 is 3deg off +x) — "
                           f"by-id lookup did not use the stored vector — "
                           f"Type4_StateLogicViolation — ranked={ranked_b}")
        else:
            print("[B] OK: baseline top neighbour is 201 (V1 cluster)")

        # ---- O: overwrite id 100 with V2 (duplicate-id upsert, last-write-wins) ----
        if not upsert(C, [{"id": 100, "vector": V2}]):
            print("SETUP_ERROR: overwrite upsert failed")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        cnt = exact_count("O", C)
        if cnt is not None and cnt != 5:
            DEFECTS.append(f"(O) exact count {cnt} != 5 after duplicate-id "
                           f"overwrite — duplicate-id leak — "
                           f"Type4_StateLogicViolation")
        else:
            print("[O] OK: count stays 5 after overwrite (id reuse)")

        # stored-state cross-check: readback vector must now be V2
        v_st = batch_get_vector("O-readback", C, 100)
        if v_st is None:
            print("SETUP_ERROR: batch-get readback of id 100 failed")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        cs_v2 = cosine(v_st, V2)
        cs_v1 = cosine(v_st, V1)
        print(f"[O-readback] cos(stored,V2)={cs_v2} cos(stored,V1)={cs_v1}")
        if cs_v2 is None or cs_v2 < 0.999 or (cs_v1 is not None and cs_v1 > cs_v2):
            DEFECTS.append(f"(O) stored vector of id 100 does not match the "
                           f"overwrite payload V2 (cos(stored,V2)={cs_v2}) — "
                           f"Type4_StateLogicViolation")
        else:
            print("[O-readback] OK: stored vector matches V2")

        # ---- R: by-id query again must reflect the NEW stored vector ----
        sR, ranked_r = byid_query("R-flip", C, 100, limit=4)
        if sR != 200 or ranked_r is None:
            print("SETUP_ERROR: post-overwrite by-id query not 200")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if not ranked_r:
            DEFECTS.append("(R) post-overwrite by-id query returned no other "
                           "points — Type4_StateLogicViolation")
        elif ranked_r[0] != 301:
            stale = " (STALE pre-overwrite vector served)" if ranked_r[0] == 201 else ""
            DEFECTS.append(f"(R) post-overwrite by-id top neighbour {ranked_r[0]} "
                           f"!= 301 (stored vector is now V2=+y){stale} — by-id "
                           f"lookup did not fetch the current stored vector — "
                           f"Type4_StateLogicViolation — ranked={ranked_r}")
        else:
            print("[R] OK: post-overwrite top neighbour is 301 (V2 cluster)")

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
