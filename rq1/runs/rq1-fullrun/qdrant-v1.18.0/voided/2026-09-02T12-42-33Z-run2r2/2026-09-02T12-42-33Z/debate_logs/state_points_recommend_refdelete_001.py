#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_recommend_refdelete_001
# strategy: delete_consistency
# endpoint: points+recommend
# constraint_ids: qdrant_behavioral_points_recommend_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/search/recommend-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: post-DELETE reference consistency of recommend (Strategy 2:
  post-DELETE consistency) x qdrant_behavioral_points_recommend_001
  "400 when a positive/negative references a point without the used vector
  or a missing point". The recommend-by-id path must dereference the
  CURRENT state of the referenced ids: once the referenced point is
  deleted, the same request that returned 200 must flip to a client
  error, and must flip BACK to 200 once the id is re-created. Legs:
  (P) seed ids 1..8; count==8 arithmetic.
  (pos) recommend(positive=[1], limit=4) -> 200 with result array
  (the promise on live reference state; no membership assertion on id 1
  itself — exclude_referenced_ids makes self-presence unspecified).
  (del) DELETE point 1 wait=true -> 200; exact count must drop 8->7.
  (neg1) recommend(positive=[1], limit=4) -> 4xx (missing reference
  point). 200 = recommend served from a ghost reference — Type4.
  (neg2) recommend(negative=[1], limit=4) -> 4xx (the assertion covers
  negative references identically). 200 = ghost via negative — Type4.
  (rec) re-upsert id 1 -> recommend(positive=[1]) -> 200 again (state
  recovery: disposition must follow the reference's current state).
  Still 4xx = stale rejection — Type4.
  (pos2) recommend(positive=[2]) -> 200 non-empty (survivor references
  unaffected by the delete — no over-deletion on the read path).
  Mutation-point justification (G6): deleting exactly the id the
  recommend fetch path dereferences empties the one state slot this
  read consumes; id-level (not collection-level) delete keeps every
  other observable alive, isolating the ghost-reference question.
  [chunk_points+recommend coverage: delete_consistency x
  qdrant_behavioral_points_recommend_001 (positive-reference ghost read
  + negative-reference ghost read + re-create recovery + survivor
  unaffected + count arithmetic 8->7)]
Oracle: (pos) recommend positive=[1] -> 200 with result array, <=4
  entries, entries carry id (contract response_shape result[].id);
  (del) delete -> 200, exact count == 7 (8-1 arithmetic);
  (neg1) recommend positive=[deleted 1] -> HTTP 4xx — 200 = ghost
  reference served (Type4_StateLogicViolation);
  (neg2) recommend negative=[deleted 1] -> HTTP 4xx — 200 = ghost
  (Type4); (rec) after re-upsert -> 200 — still 4xx = stale state
  (Type4); (pos2) positive=[2] -> 200 non-empty; 5xx with /healthz
  alive = Type3_RuntimeFailure; transport failure -> liveness re-check
  before any verdict. Exact 4xx code + raw printed for disposition
  weighing (assertion text says 400; any 4xx accepted as rejection).
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
      f"{[k for k in sorted(rt.PATHS) if k in ('recommend', 'upsert_points', 'delete_points', 'count', 'healthz')]}")

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


def delete_point(tag, coll, pid):
    s, raw = safe_request("POST", "delete_points",
                          path_params={"name": coll},
                          body={"points": [pid]},
                          query_params={"wait": "true"})
    print(f"[{tag} delete point {pid}] status={s} raw={str(raw)[:200]}")
    if handle_transport(tag, s, raw):
        return s
    return s


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spr1_" + TS + "_"
    C = PFX + "col"
    DIM = 4

    def vec(i):
        return [1.0, 0.02 * i, 0.0, 0.0]

    try:
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        if not upsert(C, [{"id": i, "vector": vec(i)} for i in range(1, 9)]):
            print("SETUP_ERROR: seed upsert failed")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if exact_count("seed", C) != 8:
            print("SETUP_ERROR: seed count != 8")
            return "SCRIPT_ERROR"

        # ---- pos: recommend with a live positive reference (the promise) ----
        s_pos, ids_pos = recommend("pos-live-ref1", C,
                                   {"positive": [1], "limit": 4})
        if s_pos != 200 or ids_pos is None:
            print("SETUP_ERROR: positive recommend not 200")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if len(ids_pos) > 4:
            DEFECTS.append(f"(pos) 200 but returned {len(ids_pos)} entries "
                           f"with limit=4 — Type4_StateLogicViolation")
        elif not ids_pos:
            DEFECTS.append("(pos) recommend 200 with EMPTY result on a "
                           "seeded 8-point collection — Type4_StateLogicViolation")
        else:
            print(f"[pos] OK: live-reference recommend returned ids={ids_pos}")

        # ---- del: delete referenced point 1 (wait=true) ----
        if delete_point("del-1", C, 1) != 200:
            print("SETUP_ERROR: delete of id 1 not 200")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        cnt = exact_count("after-del", C)
        if cnt is not None and cnt != 7:
            DEFECTS.append(f"(del) exact count {cnt} != 8-1=7 after deleting "
                           f"id 1 — Type4_StateLogicViolation")
        else:
            print("[del] OK: count 8->7 arithmetic holds")

        # ---- neg1: positive reference to the DELETED id must be rejected ----
        s_n1, ids_n1 = recommend("neg1-pos-deleted1", C,
                                 {"positive": [1], "limit": 4})
        if s_n1 == 200:
            DEFECTS.append(f"(neg1) recommend positive=[deleted id 1] "
                           f"returned 200 with ids={ids_n1} — ghost reference "
                           f"served — Type4_StateLogicViolation")
        elif s_n1 is not None and s_n1 > 0 and not (400 <= s_n1 <= 499):
            DEFECTS.append(f"(neg1) recommend positive=[deleted id 1] returned "
                           f"unexpected status {s_n1} — raw check needed")
        else:
            print(f"[neg1] OK: deleted positive reference rejected with {s_n1}")

        # ---- neg2: negative reference to the DELETED id must be rejected ----
        s_n2, ids_n2 = recommend("neg2-neg-deleted1", C,
                                 {"negative": [1], "limit": 4})
        if s_n2 == 200:
            DEFECTS.append(f"(neg2) recommend negative=[deleted id 1] "
                           f"returned 200 with ids={ids_n2} — ghost reference "
                           f"via negative — Type4_StateLogicViolation")
        elif s_n2 is not None and s_n2 > 0 and not (400 <= s_n2 <= 499):
            DEFECTS.append(f"(neg2) recommend negative=[deleted id 1] returned "
                           f"unexpected status {s_n2} — raw check needed")
        else:
            print(f"[neg2] OK: deleted negative reference rejected with {s_n2}")

        # ---- rec: re-create id 1; the disposition must flip back to 200 ----
        if not upsert(C, [{"id": 1, "vector": vec(9)}]):
            print("SETUP_ERROR: re-upsert of id 1 failed")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        cnt2 = exact_count("after-reupsert", C)
        if cnt2 is not None and cnt2 != 8:
            DEFECTS.append(f"(rec) exact count {cnt2} != 8 after re-upserting "
                           f"id 1 — Type4_StateLogicViolation")
        s_r, ids_r = recommend("rec-recreated1", C,
                               {"positive": [1], "limit": 4})
        if s_r != 200:
            if s_r is not None and s_r > 0 and 400 <= s_r <= 499:
                DEFECTS.append(f"(rec) recommend positive=[re-created id 1] "
                               f"still rejected with {s_r} after successful "
                               f"re-upsert — stale reference state — "
                               f"Type4_StateLogicViolation")
            elif s_r is not None and s_r > 0:
                print(f"[rec] note: re-created reference got status {s_r}")
        else:
            if not ids_r:
                DEFECTS.append("(rec) recommend 200 with EMPTY result on a "
                               "re-seeded collection — Type4_StateLogicViolation")
            else:
                print(f"[rec] OK: disposition flipped back to 200, ids={ids_r}")

        # ---- pos2: survivor reference unaffected ----
        s_p2, ids_p2 = recommend("pos2-survivor2", C,
                                 {"positive": [2], "limit": 4})
        if s_p2 != 200 or ids_p2 is None:
            print("SETUP_ERROR: survivor recommend not 200")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if not ids_p2:
            DEFECTS.append("(pos2) survivor recommend returned 200 with "
                           "empty result — over-deletion on the read path — "
                           "Type4_StateLogicViolation")
        else:
            print(f"[pos2] OK: survivor reference recommend returned ids={ids_p2}")

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
