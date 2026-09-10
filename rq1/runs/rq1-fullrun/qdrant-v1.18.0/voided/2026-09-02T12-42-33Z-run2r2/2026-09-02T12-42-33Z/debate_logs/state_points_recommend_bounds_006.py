#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_recommend_bounds_006
# strategy: state_bounds_validation
# endpoint: points+recommend
# constraint_ids: qdrant_range_points_recommend_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/search/recommend-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: pagination-bounds both-direction coverage x
  qdrant_range_points_recommend_001 "recommend request pagination
  bounds: limit required with minimum 1; offset minimum 0"
  (evidence_tier=explicit). G4 pairing on live seeded state — the
  boundary minima must be ACCEPTED (closure) and every value below the
  minima (or the absent limit) must be REJECTED. Legs:
  (P) seed ids 1..8; count==8.
  (pos1) limit=1, offset=0 (both boundary minima) -> 200 with <=1
  entries — the minimum legal page is served.
  (pos2) limit=8, offset=0 -> 200 with <=8 entries, non-empty (8
  candidates live; emptiness has no ground).
  (neg1) limit=0 -> 4xx (minimum 1). 200 = IllegalSuccess — Type1.
  (neg2) limit=-1 -> 4xx. 200 = IllegalSuccess.
  (neg3) offset=-1 (limit=3) -> 4xx (minimum 0). 200 = IllegalSuccess.
  (neg4) limit omitted entirely -> 4xx (limit required). 200 =
  IllegalSuccess — a silent default would contradict "required".
  (pos3) repeat of pos1 verbatim (zero mutations in between) -> 200
  again — identical read on unchanged state must not drift; a second
  4xx/5xx with nothing mutated = inconsistent read path — Type4.
  Note (R39 discipline): no oracles on result membership/scores —
  approximate-search recall is not contract-grounded; only status +
  array-shape + count bounds are adjudicated.
  [chunk_points+recommend coverage: state_bounds_validation x
  qdrant_range_points_recommend_001 (limit=0 / limit=-1 / offset=-1 /
  missing-limit rejections + limit=1/offset=0 closure positives +
  no-mutation repeat stability)]
Oracle: (pos1) limit=1 offset=0 -> 200, result array with <=1 entries;
  (pos2) limit=8 -> 200, 1..8 entries; (neg1..neg4) each violation
  body -> HTTP 4xx — 200 = Type1_IllegalSuccess (constraint minimum
  violated / required field accepted while absent); (pos3) verbatim
  repeat of pos1 -> 200 — anything else with zero mutations between =
  Type4_StateLogicViolation; 5xx with /healthz alive =
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
      f"{[k for k in sorted(rt.PATHS) if k in ('recommend', 'upsert_points', 'count', 'healthz')]}")

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


def expect_4xx(tag, s):
    """Negative-bound adjudication: 200 = IllegalSuccess, other = note."""
    if s == 200:
        DEFECTS.append(f"({tag}) returned 200 for a request violating "
                       f"qdrant_range_points_recommend_001 (limit min 1 / "
                       f"required; offset min 0) — Type1_IllegalSuccess")
    elif s is not None and s > 0 and 400 <= s <= 499:
        print(f"[{tag}] OK: violating request rejected with {s}")
    elif s is not None and s > 0:
        DEFECTS.append(f"({tag}) returned unexpected status {s} — "
                       f"raw check needed")


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spr6_" + TS + "_"
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

        # ---- pos1: boundary minima accepted (closure) ----
        s_p1, ids_p1 = recommend("pos1-limit1-offset0", C,
                                 {"positive": [1], "limit": 1, "offset": 0})
        if s_p1 != 200 or ids_p1 is None:
            print("SETUP_ERROR: limit=1/offset=0 closure positive not 200")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if len(ids_p1) > 1:
            DEFECTS.append(f"(pos1) limit=1 returned {len(ids_p1)} entries — "
                           f"Type4_StateLogicViolation")
        elif not ids_p1:
            DEFECTS.append("(pos1) limit=1 returned 200 with EMPTY result on "
                           "a seeded collection — Type4_StateLogicViolation")
        else:
            print(f"[pos1] OK: boundary minima accepted, ids={ids_p1}")

        # ---- pos2: full-width page ----
        s_p2, ids_p2 = recommend("pos2-limit8-offset0", C,
                                 {"positive": [1], "limit": 8, "offset": 0})
        if s_p2 != 200 or ids_p2 is None:
            print("SETUP_ERROR: limit=8 positive not 200")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if len(ids_p2) > 8:
            DEFECTS.append(f"(pos2) limit=8 returned {len(ids_p2)} entries — "
                           f"Type4_StateLogicViolation")
        elif not ids_p2:
            DEFECTS.append("(pos2) limit=8 returned 200 with EMPTY result on "
                           "8 live candidates — Type4_StateLogicViolation")
        else:
            print(f"[pos2] OK: full-width page returned {len(ids_p2)} entries")

        # ---- neg1: limit=0 (below minimum 1) ----
        s_n1, _ = recommend("neg1-limit0", C, {"positive": [1], "limit": 0})
        expect_4xx("neg1-limit0", s_n1)

        # ---- neg2: limit=-1 ----
        s_n2, _ = recommend("neg2-limit-neg1", C, {"positive": [1], "limit": -1})
        expect_4xx("neg2-limit-neg1", s_n2)

        # ---- neg3: offset=-1 (below minimum 0) ----
        s_n3, _ = recommend("neg3-offset-neg1", C,
                            {"positive": [1], "limit": 3, "offset": -1})
        expect_4xx("neg3-offset-neg1", s_n3)

        # ---- neg4: limit omitted (required field absent) ----
        s_n4, _ = recommend("neg4-no-limit", C, {"positive": [1]})
        expect_4xx("neg4-no-limit", s_n4)

        # ---- pos3: verbatim repeat of pos1 (zero mutations between) ----
        s_p3, ids_p3 = recommend("pos3-repeat-limit1-offset0", C,
                                 {"positive": [1], "limit": 1, "offset": 0})
        if s_p3 != 200 or ids_p3 is None:
            if s_p3 is not None and s_p3 > 0 and 400 <= s_p3 <= 499:
                DEFECTS.append(f"(pos3) verbatim repeat of the pos1 request "
                               f"was rejected with {s_p3} although NO "
                               f"mutation happened between the two reads — "
                               f"inconsistent read path — "
                               f"Type4_StateLogicViolation")
            elif s_p3 is not None and s_p3 > 0:
                print(f"[pos3] note: repeat read got status {s_p3}")
        else:
            if len(ids_p3) > 1:
                DEFECTS.append(f"(pos3) limit=1 repeat returned "
                               f"{len(ids_p3)} entries — Type4")
            else:
                print(f"[pos3] OK: identical read on unchanged state -> 200 "
                      f"again, ids={ids_p3}")

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
