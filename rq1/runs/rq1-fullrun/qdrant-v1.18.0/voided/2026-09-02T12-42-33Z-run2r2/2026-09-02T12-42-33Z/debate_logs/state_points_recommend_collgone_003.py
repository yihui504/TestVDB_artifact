#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_recommend_collgone_003
# strategy: delete_consistency
# endpoint: points+recommend
# constraint_ids: qdrant_behavioral_points_recommend_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/search/recommend-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: post-DELETE collection consistency of recommend (Strategy 2:
  post-DELETE consistency) x qdrant_behavioral_points_recommend_001
  "404 for a missing collection". The recommend read path must resolve
  the collection against CURRENT cluster state: after the collection is
  dropped, the exact request that returned 200 must return 404 — never
  200 (zombie collection read). Legs:
  (P) create + seed ids 1..4; count==4.
  (pos) recommend(positive=[1], limit=3) -> 200 result array (the
  promise on live collection state); describe -> 200 corroborates.
  (del) drop the collection (the mutation).
  (neg1) the SAME recommend body -> 404 (assertion: 404 for a missing
  collection). 200 = zombie read — Type4. Other 4xx recorded as a
  disposition note (assertion names 404); 5xx -> Type3.
  (neg2) describe on the dropped collection -> 404 (corroborates the
  collection is really gone, not a recommend-path-only anomaly).
  (neg3) recommend on a NEVER-CREATED collection name -> 404 with the
  SAME disposition as the dropped one (G9: absent-by-delete and
  absent-by-never-created are the same state and must be disposed of
  identically). 200 = phantom collection — Type4.
  Mutation-point justification (G6): collection-level drop is the
  strongest single mutation that flips the collection-existence
  precondition from true to false while leaving server and other state
  untouched — it isolates whether recommend checks existence at request
  time or serves from a stale catalog.
  [chunk_points+recommend coverage: delete_consistency x
  qdrant_behavioral_points_recommend_001 (dropped-collection 404 +
  never-created-collection 404 disposition parity + describe
  corroboration)]
Oracle: (pos) recommend on live collection -> 200 with result array;
  (neg1) the same recommend after drop -> 404 — 200 = zombie read
  (Type4_StateLogicViolation); (neg2) describe after drop -> 404;
  (neg3) recommend on never-created name -> 404 — 200 = phantom
  (Type4), and a disposition different from the dropped-collection one
  is printed for G9 weighing; 5xx with /healthz alive =
  Type3_RuntimeFailure; transport failure -> liveness re-check before
  any verdict.
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
      f"{[k for k in sorted(rt.PATHS) if k in ('recommend', 'upsert_points', 'count', 'describe_collection', 'drop_collection', 'healthz')]}")

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
    return s, [p.get("id") for p in res if isinstance(p, dict)]


def describe(tag, coll):
    s, raw = safe_request("GET", "describe_collection",
                          path_params={"name": coll})
    print(f"[{tag} describe] status={s} raw={str(raw)[:200]}")
    if handle_transport(f"{tag} describe", s, raw):
        return s
    return s


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spr3_" + TS + "_"
    C = PFX + "col"
    C_NEVER = PFX + "never_created"
    DIM = 4

    def vec(i):
        return [1.0, 0.02 * i, 0.0, 0.0]

    try:
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        if not upsert(C, [{"id": i, "vector": vec(i)} for i in range(1, 5)]):
            print("SETUP_ERROR: seed upsert failed")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if exact_count("seed", C) != 4:
            print("SETUP_ERROR: seed count != 4")
            return "SCRIPT_ERROR"

        # ---- pos: live collection ----
        if describe("pos-describe", C) != 200:
            print("SETUP_ERROR: describe of live collection not 200")
            return "SCRIPT_ERROR"
        body = {"positive": [1], "limit": 3}
        s_pos, ids_pos = recommend("pos-live-coll", C, body)
        if s_pos != 200 or ids_pos is None:
            print("SETUP_ERROR: positive recommend not 200")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if not ids_pos:
            DEFECTS.append("(pos) recommend 200 with EMPTY result on a live "
                           "seeded collection — Type4_StateLogicViolation")
        else:
            print(f"[pos] OK: live-collection recommend returned ids={ids_pos}")

        # ---- del: drop the collection (the mutation) ----
        try:
            rt.drop_collection(C)
            print(f"[del] dropped collection {C}")
        except Exception as e:
            print(f"SETUP_ERROR: drop_collection raised {e}")
            return "SCRIPT_ERROR"

        # ---- neg1: the SAME recommend body must now be 404 ----
        s_n1, ids_n1 = recommend("neg1-dropped-coll", C, body)
        if s_n1 == 200:
            DEFECTS.append(f"(neg1) recommend on DROPPED collection returned "
                           f"200 with ids={ids_n1} — zombie collection read — "
                           f"Type4_StateLogicViolation")
        elif s_n1 == 404:
            print("[neg1] OK: dropped collection recommend -> 404")
        elif s_n1 is not None and s_n1 > 0 and 400 <= s_n1 <= 499:
            print(f"[neg1] disposition note: dropped collection recommend "
                  f"-> {s_n1} (assertion names 404); raw printed above")
        elif s_n1 is not None and s_n1 > 0:
            DEFECTS.append(f"(neg1) recommend on dropped collection returned "
                           f"unexpected status {s_n1} — raw check needed")

        # ---- neg2: describe corroborates the collection is gone ----
        s_d = describe("neg2-describe-dropped", C)
        if s_d == 200:
            DEFECTS.append("(neg2) describe of DROPPED collection returned "
                           "200 — zombie in the catalog — "
                           "Type4_StateLogicViolation")
        elif s_d != 404:
            print(f"[neg2] note: describe of dropped collection -> {s_d}")

        # ---- neg3: never-created collection must share the disposition ----
        s_n3, ids_n3 = recommend("neg3-never-created", C_NEVER, body)
        if s_n3 == 200:
            DEFECTS.append(f"(neg3) recommend on NEVER-CREATED collection "
                           f"returned 200 with ids={ids_n3} — phantom "
                           f"collection — Type4_StateLogicViolation")
        elif s_n3 == 404:
            print("[neg3] OK: never-created collection recommend -> 404")
        elif s_n3 is not None and s_n3 > 0 and 400 <= s_n3 <= 499:
            print(f"[neg3] disposition note: never-created collection "
                  f"recommend -> {s_n3}; G9 parity with dropped-collection "
                  f"disposition {s_n1}: "
                  f"{'consistent' if s_n3 == s_n1 else 'INCONSISTENT — same absent-state disposed differently'}")
        elif s_n3 is not None and s_n3 > 0:
            DEFECTS.append(f"(neg3) recommend on never-created collection "
                           f"returned unexpected status {s_n3} — raw check needed")

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
