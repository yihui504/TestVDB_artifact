#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_recommend_using_vector_002
# strategy: delete_consistency
# endpoint: points+recommend
# constraint_ids: qdrant_behavioral_points_recommend_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/search/recommend-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: named-vector state flip on the `using` reference clause of
  qdrant_behavioral_points_recommend_001: "400 when a positive/negative
  references a point without the used vector ... (fetched vectors must
  match the using-vector characteristics)". Contract data type "Named
  vectors": multiple vectors per point keyed by name; `using` selects
  which vector a query targets. So the disposition of
  recommend(using=X, positive=[id]) must track whether point id
  currently HAS vector X. Legs:
  (P) named-vector collection {title, body} both dim-4 Cosine; id 1
  carries ONLY title; ids 2..5 carry both; count==5.
  (pos) recommend(using=body, positive=[2]) -> 200 result array (the
  promise on compliant vector state).
  (neg1) recommend(using=body, positive=[1]) -> 4xx (id 1 has no body
  vector). 200 = IllegalSuccess — recommend silently skipped/fetched a
  mismatched vector — Type1/Type4.
  (neg2) recommend(using=no_such_space, positive=[2]) -> 4xx (`using`
  must select an existing named vector of the collection). 200 =
  IllegalSuccess.
  (flip) re-upsert id 1 WITH body vector -> count stays 5 (upsert of an
  existing id must not add a point); recommend(using=body,
  positive=[1]) -> 200 now. Still 4xx = stale vector state — Type4.
  (pos2) recommend(using=title, positive=[1]) -> 200 (title was present
  all along — the earlier rejection must have been body-specific).
  Mutation-point justification (G6): adding exactly the missing named
  vector to exactly the rejected reference id is the minimal mutation
  that flips the using-vector precondition from false to true; nothing
  else in the collection changes, isolating whether the recommend fetch
  path reads live per-point vector state.
  [chunk_points+recommend coverage: delete_consistency x
  qdrant_behavioral_points_recommend_001 (using-vector absence
  rejection + unknown-vector-name rejection + vector-add state flip +
  title control + upsert count stability)]
Oracle: (pos) using=body positive=[2] -> 200 with result array;
  (neg1) using=body positive=[1] -> HTTP 4xx — 200 = IllegalSuccess
  (Type1_IllegalSuccess/Type4); (neg2) using=no_such_space -> 4xx —
  200 = IllegalSuccess; (flip) after upsert adds body to id 1 -> 200
  (still 4xx = stale state Type4) and exact count stays 5; (pos2)
  using=title positive=[1] -> 200 non-empty; 5xx with /healthz alive =
  Type3_RuntimeFailure; transport failure -> liveness re-check before
  any verdict. Exact 4xx codes + raws printed for disposition weighing.
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
      f"{[k for k in sorted(rt.PATHS) if k in ('recommend', 'upsert_points', 'create_collection', 'count', 'healthz')]}")

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


def recommend(tag, coll, body):
    s, raw = safe_request("POST", "recommend",
                          path_params={"name": coll}, body=body)
    print(f"[{tag} recommend] status={s} raw={str(raw)[:240]}")
    if handle_transport(tag, s, raw):
        return s, None
    if s != 200:
        return s, None
    res = result_of(raw)
    if not isinstance(res, list):
        DEFECTS.append(f"({tag}) 200 but result is not an array "
                       f"(contract response_shape: result array) — "
                       f"raw={str(raw)[:150]}")
        return s, None
    ids = [p.get("id") for p in res if isinstance(p, dict)]
    return s, ids


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spr2_" + TS + "_"
    C = PFX + "col"
    DIM = 4

    def vec(i):
        return [1.0, 0.02 * i, 0.0, 0.0]

    def wvec(i):
        return [0.0, 0.0, 1.0, 0.02 * i]

    try:
        # named-vector collection: title + body, both dim-4 Cosine
        s_cr, raw_cr = safe_request("PUT", "create_collection",
                                    path_params={"name": C},
                                    body={"vectors": {
                                        "title": {"size": DIM, "distance": "Cosine"},
                                        "body": {"size": DIM, "distance": "Cosine"},
                                    }})
        print(f"[create named-vector collection] status={s_cr} raw={str(raw_cr)[:200]}")
        if handle_transport("create_collection", s_cr, raw_cr):
            return "SCRIPT_ERROR"
        if s_cr not in (200, 201):
            print(f"SETUP_ERROR: named-vector create returned {s_cr}")
            return "SCRIPT_ERROR"

        seed = [{"id": 1, "vector": {"title": vec(1)}}]  # title ONLY
        for i in range(2, 6):  # ids 2..5 carry both vectors
            seed.append({"id": i, "vector": {"title": vec(i), "body": wvec(i)}})
        if not upsert(C, seed):
            print("SETUP_ERROR: seed upsert failed")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if exact_count("seed", C) != 5:
            print("SETUP_ERROR: seed count != 5")
            return "SCRIPT_ERROR"

        # ---- pos: reference that HAS the used vector ----
        s_pos, ids_pos = recommend("pos-body-ref2", C,
                                   {"using": "body", "positive": [2], "limit": 3})
        if s_pos != 200 or ids_pos is None:
            print("SETUP_ERROR: positive using=body recommend not 200")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if not ids_pos:
            DEFECTS.append("(pos) using=body recommend 200 with EMPTY result "
                           "on compliant state — Type4_StateLogicViolation")
        else:
            print(f"[pos] OK: using=body positive=[2] returned ids={ids_pos}")

        # ---- neg1: reference id LACKS the used vector -> must be rejected ----
        s_n1, ids_n1 = recommend("neg1-body-ref1-lacks", C,
                                 {"using": "body", "positive": [1], "limit": 3})
        if s_n1 == 200:
            DEFECTS.append(f"(neg1) using=body positive=[1] (point without a "
                           f"body vector) returned 200 with ids={ids_n1} — "
                           f"IllegalSuccess: fetched vectors must match the "
                           f"using-vector characteristics — Type1_IllegalSuccess")
        elif s_n1 is not None and s_n1 > 0 and not (400 <= s_n1 <= 499):
            DEFECTS.append(f"(neg1) using=body positive=[1] returned unexpected "
                           f"status {s_n1} — raw check needed")
        else:
            print(f"[neg1] OK: using-vector absence rejected with {s_n1}")

        # ---- neg2: unknown vector name -> must be rejected ----
        s_n2, ids_n2 = recommend("neg2-unknown-space", C,
                                 {"using": "no_such_space", "positive": [2], "limit": 3})
        if s_n2 == 200:
            DEFECTS.append(f"(neg2) using=no_such_space returned 200 with "
                           f"ids={ids_n2} — IllegalSuccess: `using` must select "
                           f"an existing named vector — Type1_IllegalSuccess")
        elif s_n2 is not None and s_n2 > 0 and not (400 <= s_n2 <= 499):
            DEFECTS.append(f"(neg2) using=no_such_space returned unexpected "
                           f"status {s_n2} — raw check needed")
        else:
            print(f"[neg2] OK: unknown vector name rejected with {s_n2}")

        # ---- flip: add the body vector to id 1; disposition must flip to 200 ----
        if not upsert(C, [{"id": 1, "vector": {"title": vec(1), "body": wvec(9)}}]):
            print("SETUP_ERROR: flip upsert failed")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        cnt2 = exact_count("after-flip", C)
        if cnt2 is not None and cnt2 != 5:
            DEFECTS.append(f"(flip) exact count {cnt2} != 5 after re-upserting "
                           f"EXISTING id 1 — upsert is insert-or-update, must "
                           f"not add a point — Type4_StateLogicViolation")
        s_f, ids_f = recommend("flip-body-ref1-now-has", C,
                               {"using": "body", "positive": [1], "limit": 3})
        if s_f != 200:
            if s_f is not None and s_f > 0 and 400 <= s_f <= 499:
                DEFECTS.append(f"(flip) using=body positive=[1] still rejected "
                               f"with {s_f} after the body vector was upserted — "
                               f"stale per-point vector state — "
                               f"Type4_StateLogicViolation")
            elif s_f is not None and s_f > 0:
                print(f"[flip] note: re-created vector reference got status {s_f}")
        else:
            if not ids_f:
                DEFECTS.append("(flip) using=body positive=[1] 200 with EMPTY "
                               "result after vector added — Type4_StateLogicViolation")
            else:
                print(f"[flip] OK: disposition flipped to 200, ids={ids_f}")

        # ---- pos2: title control (present all along) ----
        s_p2, ids_p2 = recommend("pos2-title-ref1", C,
                                 {"using": "title", "positive": [1], "limit": 3})
        if s_p2 != 200 or ids_p2 is None:
            print("SETUP_ERROR: title-control recommend not 200")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if not ids_p2:
            DEFECTS.append("(pos2) using=title positive=[1] 200 with empty "
                           "result — title vector existed all along — "
                           "Type4_StateLogicViolation")
        else:
            print(f"[pos2] OK: title control returned ids={ids_p2}")

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
