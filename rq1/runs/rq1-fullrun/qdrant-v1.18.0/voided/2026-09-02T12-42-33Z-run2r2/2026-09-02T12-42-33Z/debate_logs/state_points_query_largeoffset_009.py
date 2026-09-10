#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_query_largeoffset_009
# strategy: count_consistency
# endpoint: points+query
# constraint_ids: qdrant_behavioral_points_query_002
# source_url: https://qdrant.tech/documentation/search/search/
# doc_version: current (site latest; no version archive)
"""
Attack: large-offset read-only legality and state preservation x
  qdrant_behavioral_points_query_002 "large offsets are legal but may
  degrade performance; slowness on large offsets is documented, not a
  defect". SKIPPED: by-design per threat_model — LATENCY of large-offset
  queries is documented behavior and is NOT judged here (a timeout with
  the service still alive is recorded as the documented-slowness path,
  never a defect); only correctness and read-only state preservation are
  adjudicated. Seed 12 points (exact=true used for the arithmetic legs to
  keep HNSW by-design noise out of the oracle). Legs:
  (A5) offset=5, limit=10, exact -> 200 with exactly 12-5=7 points
  (offset arithmetic on a legal in-range offset).
  (B11) offset=11 -> exactly 1 point; (B12) offset=12 (== count,
  boundary closure) -> 200 with 0 points — a legal offset equal to the
  collection size is an empty page, not an error.
  (C1e9) offset=1_000_000_000 (far beyond size) -> 200 with 0 points
  and no next_page_offset — the documented contract for out-of-range
  offsets is empty, not 5xx.
  (D1e9) same extreme offset on the no-query id-ordered face -> 200
  with 0 points.
  (RO) exact count before == after == 12: a read-only query must not
  mutate state.
  Mutation-point justification (G6): offset extremes on a read-only
  endpoint are the classic side-effect leak vector — a paged reader that
  accidentally truncates/deletes (e.g. misrouted to a maintenance path)
  shows up as a count drop with no other observable changing.
  [chunk_points+query coverage: count_consistency x
  qdrant_behavioral_points_query_002 (in-range offset arithmetic +
  offset==count boundary + 1e9 offset empty-page + no-query face +
  read-only count preservation)]
Oracle: (A5) 200 with exactly 7 ids; (B11) 200 with exactly 1 id;
  (B12) 200 with 0 ids (non-200 = boundary mishandled,
  Type4_StateLogicViolation); (C1e9)/(D1e9) 200 with 0 ids and
  next_page_offset absent/null — 5xx with /healthz alive =
  Type3_RuntimeFailure; (RO) exact count stays 12 before/after every leg
  (count change = Type4_StateLogicViolation); timeout on the extreme
  offset with service alive = documented-slowness path, recorded as
  note (NOT a defect per the constraint text), script continues;
  transport failure with dead service -> liveness re-check before any
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

print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if k in ('query', 'upsert_points', 'count')]}")

DEFECTS = []
NOTES = []
ABORT = [False]

N = 12
BIG = 1_000_000_000


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
    print(f"[liveness {tag}] healthz probe required")
    _hs, _hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={_hs} raw={str(_hraw)[:120]}")
    return _hs == 200


def exact_count(tag, coll):
    s, raw = safe_request("POST", "count", path_params={"name": coll},
                          body={"exact": True})
    print(f"[{tag} count] status={s} raw={str(raw)[:160]}")
    if s == 0:
        if not liveness(f"{tag} count"):
            ABORT[0] = True
        return None
    if 500 <= s <= 599:
        if liveness(f"{tag} count"):
            DEFECTS.append(f"({tag} count) returned {s} with service alive "
                           f"— Type3_RuntimeFailure")
        else:
            ABORT[0] = True
        return None
    if s != 200:
        print(f"SETUP_ERROR: {tag} count returned {s}")
        return None
    try:
        cnt = json.loads(raw).get("result", {}).get("count")
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        cnt = None
    if isinstance(cnt, bool) or not isinstance(cnt, int):
        print(f"SETUP_ERROR: {tag} count result.count missing — "
              f"raw={str(raw)[:200]}")
        return None
    return cnt


def offset_leg(tag, coll, body, expect_n, timeout=30, check_npo=False):
    """Returns True if the leg matched its expectation."""
    t0 = time.time()
    s, raw = safe_request("POST", "query", path_params={"name": coll},
                          body=body, timeout=timeout)
    dt = time.time() - t0
    print(f"[{tag}] status={s} elapsed={dt:.2f}s raw={str(raw)[:220]}")
    if s == 0:
        # transport failure or timeout: distinguish documented slowness from
        # a dead service via the lightweight health endpoint
        if liveness(tag):
            low = str(raw).lower()
            if "timeout" in low or "timed out" in low:
                NOTES.append(f"({tag}) request timed out after {timeout}s "
                             f"with /healthz alive — documented large-offset "
                             f"slowness per qdrant_behavioral_points_query_002 "
                             f"(latency is NOT judged; recorded only)")
                print(f"[{tag}] NOTE: documented-slowness path, not a defect")
                return True
            DEFECTS.append(f"({tag}) transport failure with service alive — "
                           f"raw={str(raw)[:150]}")
            return False
        ABORT[0] = True
        return False
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) large-offset query returned {s} with "
                           f"service alive — documented contract for "
                           f"out-of-range offsets is an EMPTY page, not an "
                           f"internal error — Type3_RuntimeFailure — "
                           f"raw={str(raw)[:150]}")
        else:
            ABORT[0] = True
        return False
    if s != 200:
        DEFECTS.append(f"({tag}) legal offset query returned {s} (constraint: "
                       f"large offsets are LEGAL; out-of-range offsets yield "
                       f"an empty page) — Type4_StateLogicViolation — "
                       f"raw={str(raw)[:150]}")
        return False
    try:
        res = json.loads(raw).get("result")
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        res = None
    pts = res.get("points") if isinstance(res, dict) else None
    if not isinstance(pts, list):
        DEFECTS.append(f"({tag}) 200 but result.points is not an array — "
                       f"raw={str(raw)[:150]}")
        return False
    if len(pts) != expect_n:
        DEFECTS.append(f"({tag}) expected {expect_n} points at this offset, "
                       f"got {len(pts)} — offset arithmetic broken — "
                       f"Type4_StateLogicViolation — ids="
                       f"{[p.get('id') for p in pts if isinstance(p, dict)]}")
        return False
    if check_npo:
        npo = res.get("next_page_offset") if isinstance(res, dict) else "x"
        if npo is not None:
            DEFECTS.append(f"({tag}) empty terminal page carried "
                           f"next_page_offset={npo!r} — pagination state "
                           f"inconsistent — Type4_StateLogicViolation")
    print(f"[{tag}] OK: 200 with {expect_n} points")
    return True


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spq9_" + TS + "_"
    C = PFX + "col"
    DIM = 4

    def vec(i):
        return [1.0, 0.01 * (i % 12), 0.0, 0.0]

    try:
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        s_up, raw_up = safe_request("PUT", "upsert_points",
                                    path_params={"name": C},
                                    body={"points": [{"id": i, "vector": vec(i)}
                                                     for i in range(N)]},
                                    query_params={"wait": "true"})
        print(f"[seed upsert {N}] status={s_up} raw={str(raw_up)[:160]}")
        if s_up == 0 or 500 <= s_up <= 599:
            if s_up == 0 and not liveness("seed"):
                return "SCRIPT_ERROR"
            if 500 <= s_up <= 599 and liveness("seed"):
                DEFECTS.append(f"(seed) upsert returned {s_up} — "
                               f"Type3_RuntimeFailure")
                return "DEFECT_FOUND"
            return "SCRIPT_ERROR"
        if s_up != 200:
            print("SETUP_ERROR: seed upsert failed")
            return "SCRIPT_ERROR"
        cnt0 = exact_count("before", C)
        if cnt0 != N:
            print(f"SETUP_ERROR: seed count {cnt0} != {N}")
            return "SCRIPT_ERROR"

        qvec = [1.0, 0.0, 0.0, 0.0]
        # ---- A5: in-range offset arithmetic (12-5=7) ----
        offset_leg("A5-offset5", C,
                   {"query": qvec, "limit": 10, "offset": 5,
                    "params": {"exact": True}}, 7)
        # ---- B11: last-point offset (12-11=1) ----
        offset_leg("B11-offset11", C,
                   {"query": qvec, "limit": 10, "offset": 11,
                    "params": {"exact": True}}, 1)
        # ---- B12: offset == count boundary closure -> empty page ----
        offset_leg("B12-offset12-boundary", C,
                   {"query": qvec, "limit": 10, "offset": 12,
                    "params": {"exact": True}}, 0, check_npo=True)
        # ---- C1e9: far-out-of-range offset -> empty page, never 5xx ----
        offset_leg("C1e9-offset-1e9", C,
                   {"query": qvec, "limit": 10, "offset": BIG}, 0,
                   timeout=60, check_npo=True)
        # ---- D1e9: same extreme offset on the no-query id-ordered face ----
        offset_leg("D1e9-noquery-offset-1e9", C,
                   {"limit": 10, "offset": BIG}, 0,
                   timeout=60, check_npo=True)
        # ---- RO: read-only preservation ----
        cnt1 = exact_count("after", C)
        if cnt1 is not None and cnt1 != N:
            DEFECTS.append(f"(RO) exact count changed {cnt0} -> {cnt1} after "
                           f"read-only offset queries — read path mutated "
                           f"state — Type4_StateLogicViolation")
        elif cnt1 is not None:
            print(f"[RO] OK: count unchanged at {N}")

        for n_ in NOTES:
            print(f"NOTE: {n_}")
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
