#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_query_noquery_idorder_006
# strategy: count_consistency
# endpoint: points+query
# constraint_ids: qdrant_behavioral_points_query_004
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: query-absent no-prefetch id-ordering contract (Strategy 1 flavor:
  read-path state consistency vs seeded-set arithmetic) x
  qdrant_behavioral_points_query_004 "query absent and no prefetch: the
  response contains points ordered by their ids (OpenAPI QueryRequest
  description)". Seed 10 ids in shuffled upsert order [500,42,917,13,700,
  88,231,56,9,3] — digit-length variety so NUMERIC ascending
  (3,9,13,42,56,88,231,500,700,917) differs from lexicographic
  ("13"<"231"<"3"<"42"<"500"<"56"<"700"<"88"<"9"<"917"): a lexicographic
  sort fails the oracle. Legs:
  (A) POST query body {"limit": 10} — NO query key, NO prefetch key ->
  must be 200 (400 would contradict the documented no-query behavior)
  and result.points ids must form the complete seeded set in a total
  NUMERIC id order; primary expectation ascending (qdrant id-ordered
  semantics); strictly-descending is recorded as WARN (the spec text does
  not pin direction) while any non-monotonic order is a hard defect.
  (B) delete ids {42,500} wait=true -> re-query: ascending order minus
  the deleted ids, count arithmetic 10->8; deleted ids reappearing =
  zombie read.
  (C) offset pagination without query: {"limit":3}, then offsets 3 and 6
  -> pages concatenate to the same global order, complete, duplicate-free
  (page sizes 3,3,2 arithmetic).
  Mutation-point justification (G6): point deletion between two no-query
  reads is the cheapest mutation that makes an id-ordered listing drift
  if the ordering/read path is served from a stale snapshot.
  [chunk_points+query coverage: count_consistency x
  qdrant_behavioral_points_query_004 (no-query 200 + numeric id order +
  lexicographic trap + post-delete ordering + offset pagination
  completeness)]
Oracle: (A) HTTP 200 (400 = documented no-query behavior not implemented
  — Type4_StateLogicViolation/doc-consistency) with the exact seeded id
  set, numerically monotonic (non-monotonic = Type4; strictly descending
  = WARN only); (B) post-delete sequence == ascending seeded order minus
  {42,500} and exact count == 8 (zombie id = Type4; wrong count =
  Type4); (C) pages 3/3/2 concatenate monotonically with no loss/dup
  (Type4 otherwise); 5xx with /healthz alive = Type3_RuntimeFailure;
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
      f"{[k for k in sorted(rt.PATHS) if k in ('query', 'upsert_points', 'delete_points', 'count')]}")

DEFECTS = []
WARNINGS = []
ABORT = [False]

SEED_IDS = [500, 42, 917, 13, 700, 88, 231, 56, 9, 3]
DELETE_IDS = [42, 500]


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


def noquery_read(tag, coll, body):
    """POST query with NO query key and NO prefetch key in the body."""
    s, raw = safe_request("POST", "query", path_params={"name": coll}, body=body)
    print(f"[{tag} body={json.dumps(body)}] status={s} raw={str(raw)[:240]}")
    if handle_transport(tag, s, raw):
        return s, None
    if s != 200:
        return s, None
    try:
        res = json.loads(raw).get("result")
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        res = None
    pts = res.get("points") if isinstance(res, dict) else None
    if not isinstance(pts, list):
        DEFECTS.append(f"({tag}) 200 but result.points is not an array "
                       f"(contract response_shape) — raw={str(raw)[:150]}")
        return s, None
    return s, [p.get("id") for p in pts if isinstance(p, dict)]


def is_numerically_monotonic(ids):
    asc = all(ids[i] < ids[i + 1] for i in range(len(ids) - 1))
    desc = all(ids[i] > ids[i + 1] for i in range(len(ids) - 1))
    return asc, desc


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spq6_" + TS + "_"
    C = PFX + "col"
    DIM = 4

    def vec(i):
        return [1.0, 0.001 * i, 0.0, 0.0]

    try:
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        s_up, raw_up = safe_request("PUT", "upsert_points",
                                    path_params={"name": C},
                                    body={"points": [{"id": i, "vector": vec(i)}
                                                     for i in SEED_IDS]},
                                    query_params={"wait": "true"})
        print(f"[seed upsert {len(SEED_IDS)}] status={s_up} raw={str(raw_up)[:160]}")
        if handle_transport("seed upsert", s_up, raw_up) or s_up != 200:
            print("SETUP_ERROR: seed upsert failed")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"

        # ---- A: no query, no prefetch ----
        sA, idsA = noquery_read("A-noquery", C, {"limit": 10})
        if sA is not None and sA > 0 and sA != 200:
            DEFECTS.append(f"(A) no-query no-prefetch request returned {sA} "
                           f"(OpenAPI: query may be missing without prefetch; "
                           f"response is points ordered by id) — documented "
                           f"behavior not implemented — "
                           f"Type4_StateLogicViolation")
        if idsA is not None:
            print(f"[A] returned ids: {idsA}")
            if sorted(idsA) != sorted(SEED_IDS):
                missing = sorted(set(SEED_IDS) - set(idsA))
                extra = sorted(set(idsA) - set(SEED_IDS))
                DEFECTS.append(f"(A) no-query listing set mismatch — missing "
                               f"{missing} extra {extra} — "
                               f"Type4_StateLogicViolation")
            asc, desc = is_numerically_monotonic(idsA)
            if not asc and not desc:
                DEFECTS.append(f"(A) no-query listing is not numerically "
                               f"monotonic by id: {idsA} — violates 'points "
                               f"ordered by their ids' — "
                               f"Type4_StateLogicViolation")
            elif asc:
                if idsA != sorted(SEED_IDS):
                    DEFECTS.append(f"(A) ascending but != sorted numeric ids "
                                   f"(lexicographic sort?): {idsA} — "
                                   f"Type4_StateLogicViolation")
                else:
                    print("[A] OK: numeric ascending id order, complete set")
            else:
                WARNINGS.append(f"(A) strictly DESCENDING id order returned "
                                f"({idsA}); spec text does not pin direction — "
                                f"recorded as observation")

        # ---- B: delete two ids, re-read ----
        s_d, raw_d = safe_request("POST", "delete_points",
                                  path_params={"name": C},
                                  body={"points": DELETE_IDS},
                                  query_params={"wait": "true"})
        print(f"[B delete {DELETE_IDS}] status={s_d} raw={str(raw_d)[:200]}")
        if handle_transport("B delete", s_d, raw_d) or s_d != 200:
            print("SETUP_ERROR: delete failed")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        s_ct, raw_ct = safe_request("POST", "count", path_params={"name": C},
                                    body={"exact": True})
        print(f"[B count] status={s_ct} raw={str(raw_ct)[:160]}")
        if handle_transport("B count", s_ct, raw_ct):
            print("SETUP_ERROR: count failed post-delete")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        try:
            cnt = json.loads(raw_ct).get("result", {}).get("count")
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
            cnt = None
        if isinstance(cnt, int) and cnt != 8:
            DEFECTS.append(f"(B) exact count {cnt} != 10-2=8 after deleting "
                           f"{DELETE_IDS} — Type4_StateLogicViolation")
        sB, idsB = noquery_read("B-postdelete", C, {"limit": 10})
        if idsB is not None:
            print(f"[B] returned ids: {idsB}")
            expected = sorted(i for i in SEED_IDS if i not in DELETE_IDS)
            if sorted(idsB) != expected:
                zombie = sorted(set(DELETE_IDS) & set(idsB))
                missing = sorted(set(expected) - set(idsB))
                DEFECTS.append(f"(B) post-delete listing mismatch — zombie "
                               f"{zombie} missing {missing} — "
                               f"Type4_StateLogicViolation")
            ascB, _ = is_numerically_monotonic(idsB)
            if not ascB:
                WARNINGS.append(f"(B) post-delete listing not ascending "
                                f"({idsB}); monotonicity already adjudicated "
                                f"in (A)")
            else:
                print("[B] OK: post-delete ascending order, zombies absent")

        # ---- C: offset pagination without query ----
        sC0, p0 = noquery_read("C-page0", C, {"limit": 3})
        sC3, p3 = noquery_read("C-page3", C, {"limit": 3, "offset": 3})
        sC6, p6 = noquery_read("C-page6", C, {"limit": 3, "offset": 6})
        if None not in (p0, p3, p6):
            sizes = [len(p0), len(p3), len(p6)]
            cat = p0 + p3 + p6
            print(f"[C] pages {p0} {p3} {p6} sizes={sizes}")
            if sizes != [3, 3, 2]:
                DEFECTS.append(f"(C) page sizes {sizes} != arithmetic "
                               f"[3,3,2] for 8 remaining points at limit 3 — "
                               f"Type4_StateLogicViolation")
            if len(set(cat)) != len(cat):
                DEFECTS.append(f"(C) duplicate ids across no-query pages: "
                               f"{cat} — Type4_StateLogicViolation")
            expected = sorted(i for i in SEED_IDS if i not in DELETE_IDS)
            if sorted(cat) != expected:
                DEFECTS.append(f"(C) paginated union {sorted(cat)} != "
                               f"remaining ids {expected} — "
                               f"Type4_StateLogicViolation")
            ascC, _ = is_numerically_monotonic(cat)
            if not ascC:
                DEFECTS.append(f"(C) concatenated no-query pages not "
                               f"numerically monotonic: {cat} — offset "
                               f"pagination broke id ordering — "
                               f"Type4_StateLogicViolation")
            else:
                print("[C] OK: paginated union complete and monotonic")

        for w in WARNINGS:
            print(f"WARN: {w}")
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
