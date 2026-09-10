#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_recommend_lookupfrom_004
# strategy: delete_consistency
# endpoint: points+recommend
# constraint_ids: qdrant_behavioral_points_recommend_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/search/recommend-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: cross-collection reference state via lookup_from x
  qdrant_behavioral_points_recommend_001 ("404 for a missing
  collection"). With lookup_from={collection: B}, the recommend run on
  collection A dereferences reference ids against B's CURRENT state, so
  the request's legality depends on a collection OTHER than the one in
  the URL path. Dropping B must flip the request from 200 to a client
  error. Legs:
  (P) collections A and B (both dim-4 Cosine); B seeded ids 1..4
  (reference vectors), A seeded ids 11..14 (search candidates).
  (pos) recommend(A, positive=[1], lookup_from={collection: B},
  limit=3) -> 200 result array (references resolved from live B).
  (del) drop B (the mutation touches ONLY the lookup side; A stays).
  (neg1) the same lookup_from request -> 404 (the lookup collection is
  a missing collection per the assertion). 200 = recommend consumed
  phantom cross-collection state — IllegalSuccess. 5xx -> Type3.
  (neg2) lookup_from={collection: never-created name} -> the SAME 404
  disposition (G9: absent-by-delete vs absent-by-never-created must be
  disposed of identically). 200 = phantom.
  (pos2) plain recommend(A, positive=[11]) with NO lookup_from -> 200
  (A itself intact — the drop of B must not damage the searching
  collection's read path).
  Mutation-point justification (G6): dropping the lookup collection is
  the unique mutation that invalidates ONLY the reference-resolution
  dependency of this request — both the URL collection and the
  reference ids stay constant, isolating whether lookup resolution
  re-checks collection existence at request time.
  [chunk_points+recommend coverage: delete_consistency x
  qdrant_behavioral_points_recommend_001 (lookup_from.collection
  dropped -> 404 + never-created parity + searching-collection
  collateral check)]
Oracle: (pos) lookup_from recommend on live B -> 200 with result
  array; (neg1) the same request after dropping B -> 404 — 200 =
  IllegalSuccess on phantom lookup state (Type1_IllegalSuccess);
  (neg2) lookup_from to a never-created collection -> 404 with the
  same disposition (200 = phantom); (pos2) plain recommend on A ->
  200 non-empty; 5xx with /healthz alive = Type3_RuntimeFailure;
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

print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if k in ('recommend', 'upsert_points', 'count', 'drop_collection', 'healthz')]}")

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
    print(f"[upsert {coll} {len(points)} pts] status={s} raw={str(raw)[:160]}")
    if handle_transport("upsert", s, raw):
        return False
    return s == 200


def exact_count(tag, coll):
    s, raw = safe_request("POST", "count", path_params={"name": coll},
                          body={"exact": True})
    print(f"[{tag} count {coll}] status={s} raw={str(raw)[:160]}")
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
    print(f"[{tag} recommend {coll}] status={s} raw={str(raw)[:240]}")
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


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spr4_" + TS + "_"
    A = PFX + "a"      # searching collection (URL path)
    B = PFX + "b"      # lookup collection (reference vectors)
    B_NEVER = PFX + "never"
    DIM = 4

    def vec(i):
        return [1.0, 0.02 * i, 0.0, 0.0]

    try:
        okA, errA = rt.setup_default(A, DIM, "Cosine")
        okB, errB = rt.setup_default(B, DIM, "Cosine")
        if not (okA and okB):
            print(f"SETUP_ERROR: setup_default failed A={errA} B={errB}")
            return "SCRIPT_ERROR"
        if not upsert(B, [{"id": i, "vector": vec(i)} for i in range(1, 5)]):
            print("SETUP_ERROR: seed upsert to B failed")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if not upsert(A, [{"id": i, "vector": vec(i)} for i in range(11, 15)]):
            print("SETUP_ERROR: seed upsert to A failed")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if exact_count("seed", B) != 4 or exact_count("seed", A) != 4:
            print("SETUP_ERROR: seed counts != 4/4")
            return "SCRIPT_ERROR"

        # ---- pos: lookup_from against a LIVE lookup collection ----
        body_lookup = {"positive": [1], "limit": 3,
                       "lookup_from": {"collection": B}}
        s_pos, ids_pos = recommend("pos-lookup-live-B", A, body_lookup)
        if s_pos != 200 or ids_pos is None:
            print("SETUP_ERROR: positive lookup_from recommend not 200")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if not ids_pos:
            DEFECTS.append("(pos) lookup_from recommend 200 with EMPTY result "
                           "on live A+B — Type4_StateLogicViolation")
        else:
            print(f"[pos] OK: lookup_from (live B) returned ids={ids_pos}")

        # ---- del: drop ONLY the lookup collection ----
        try:
            rt.drop_collection(B)
            print(f"[del] dropped lookup collection {B}")
        except Exception as e:
            print(f"SETUP_ERROR: drop_collection(B) raised {e}")
            return "SCRIPT_ERROR"

        # ---- neg1: same lookup_from request must now fail (missing collection) ----
        s_n1, ids_n1 = recommend("neg1-lookup-dropped-B", A, body_lookup)
        if s_n1 == 200:
            DEFECTS.append(f"(neg1) lookup_from recommend resolved against a "
                           f"DROPPED collection and returned 200 with "
                           f"ids={ids_n1} — phantom cross-collection state — "
                           f"Type1_IllegalSuccess")
        elif s_n1 == 404:
            print("[neg1] OK: dropped lookup collection -> 404")
        elif s_n1 is not None and s_n1 > 0 and 400 <= s_n1 <= 499:
            print(f"[neg1] disposition note: dropped lookup collection -> "
                  f"{s_n1} (assertion: 404 for a missing collection); "
                  f"raw printed above")
        elif s_n1 is not None and s_n1 > 0:
            DEFECTS.append(f"(neg1) lookup_from to dropped collection returned "
                           f"unexpected status {s_n1} — raw check needed")

        # ---- neg2: never-created lookup collection — same disposition (G9) ----
        body_never = {"positive": [1], "limit": 3,
                      "lookup_from": {"collection": B_NEVER}}
        s_n2, ids_n2 = recommend("neg2-lookup-never-created", A, body_never)
        if s_n2 == 200:
            DEFECTS.append(f"(neg2) lookup_from to a NEVER-CREATED collection "
                           f"returned 200 with ids={ids_n2} — phantom — "
                           f"Type1_IllegalSuccess")
        elif s_n2 == 404:
            print("[neg2] OK: never-created lookup collection -> 404")
        elif s_n2 is not None and s_n2 > 0 and 400 <= s_n2 <= 499:
            print(f"[neg2] disposition note: never-created lookup -> {s_n2}; "
                  f"G9 parity with dropped-lookup disposition {s_n1}: "
                  f"{'consistent' if s_n2 == s_n1 else 'INCONSISTENT — same absent-state disposed differently'}")
        elif s_n2 is not None and s_n2 > 0:
            DEFECTS.append(f"(neg2) lookup_from to never-created collection "
                           f"returned unexpected status {s_n2} — raw check needed")

        # ---- pos2: A itself must be unharmed ----
        s_p2, ids_p2 = recommend("pos2-plain-on-A", A,
                                 {"positive": [11], "limit": 3})
        if s_p2 != 200 or ids_p2 is None:
            print("SETUP_ERROR: plain recommend on A not 200 after dropping B")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if not ids_p2:
            DEFECTS.append("(pos2) plain recommend on A 200 with EMPTY result "
                           "after dropping B — collateral damage to the "
                           "searching collection — Type4_StateLogicViolation")
        else:
            print(f"[pos2] OK: plain recommend on A returned ids={ids_p2}")

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        if ABORT[0]:
            print("ABORT: environment/transport unavailable mid-run")
            return "SCRIPT_ERROR"
        return "NO_DEFECT"
    finally:
        for _c in (A, B):
            try:
                rt.drop_collection(_c)
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
