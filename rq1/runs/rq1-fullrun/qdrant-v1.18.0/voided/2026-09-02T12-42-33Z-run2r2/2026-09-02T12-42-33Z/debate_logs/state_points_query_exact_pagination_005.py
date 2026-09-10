#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_query_exact_pagination_005
# strategy: count_consistency
# endpoint: points+query
# constraint_ids: qdrant_behavioral_points_query_003
# source_url: https://qdrant.tech/documentation/search/search/
# doc_version: current (site latest; no version archive)
"""
Attack: exact=true offset-pagination stability and completeness
  (Strategy 1 flavor: read-path state consistency vs arithmetic oracle) x
  qdrant_behavioral_points_query_003 "using exact=true gives stable
  ordering for offset pagination". SKIPPED: by-design per threat_model —
  the non-exact HNSW duplicate/skip-across-pages behavior (issue #9523)
  is a maintainer-confirmed limitation and is NOT attacked here; only the
  exact=true promise is attacked. Setup: Dot-distance collection (score =
  dot product = pure arithmetic, no cosine normalization in the oracle —
  R27 discipline), 40 points with DISTINCT first components a_i = 0.05 +
  ((i*7) % 40)/40 (permutation, so id order != score order and no ties),
  query vector = e1. Legs:
  (E1) paginate limit=7 with explicit offsets 0,7,...,35 using
  params={"exact": true}: concatenated ids must equal the arithmetic
  descending-score order, cover all 40 ids exactly once (page sizes
  7,7,7,7,7,5; no loss, no dup, no cross-page regression).
  (E2) run the identical pagination a second time: the full sequence must
  be byte-identical to run 1 (the documented stability promise of
  exact=true).
  (E3) next_page_offset observation: present on non-final pages and
  absent/null on the final page (soft oracle — recorded, WARN only if
  the shape deviates, since offset arithmetic is adjudicated explicitly).
  [chunk_points+query coverage: count_consistency x
  qdrant_behavioral_points_query_003 (exact pagination completeness +
  arithmetic ordering + run-to-run stability + page-size arithmetic)]
Oracle: (E1) every page 200, concatenated id sequence ==
  arithmetic descending-dot order (any loss/dup/reorder =
  Type4_StateLogicViolation); page sizes exactly [7,7,7,7,7,5] for 40
  points at limit 7; (E2) second run sequence identical to first — a
  differing sequence violates the documented exact=true stability
  (Type4_StateLogicViolation); (E3) final page has no next_page_offset;
  5xx with /healthz alive = Type3_RuntimeFailure; transport failure ->
  liveness re-check before any verdict.
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
      f"{[k for k in sorted(rt.PATHS) if k in ('query', 'upsert_points', 'count', 'create_collection')]}")

DEFECTS = []
WARNINGS = []
ABORT = [False]

N_POINTS = 40
LIMIT = 7
DIM = 8
QUERY_VEC = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def a_of(i):
    """Distinct first components; (i*7) % 40 is a permutation of 0..39."""
    return 0.05 + ((i * 7) % 40) / 40.0


def expected_order():
    """Arithmetic descending-dot ranking: a desc -> id (1000+i) desc by a."""
    pairs = sorted(((a_of(i), 1000 + i) for i in range(N_POINTS)),
                   key=lambda t: -t[0])
    return [pid for _, pid in pairs]


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


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spq5_" + TS + "_"
    C = PFX + "col"

    try:
        # Dot distance so score == dot == a_i (arithmetic oracle, R27-safe)
        s_c, raw_c = safe_request("PUT", "create_collection",
                                  path_params={"name": C},
                                  body={"vectors": {"size": DIM,
                                                    "distance": "Dot"}})
        print(f"[create Dot dim{DIM}] status={s_c} raw={str(raw_c)[:160]}")
        if handle_transport("create", s_c, raw_c) or s_c not in (200, 201):
            print("SETUP_ERROR: create failed")
            return "SCRIPT_ERROR"
        pts = [{"id": 1000 + i,
                "vector": [a_of(i)] + [0.0] * (DIM - 1)}
               for i in range(N_POINTS)]
        s_up, raw_up = safe_request("PUT", "upsert_points",
                                    path_params={"name": C},
                                    body={"points": pts},
                                    query_params={"wait": "true"})
        print(f"[seed upsert {N_POINTS}] status={s_up} raw={str(raw_up)[:160]}")
        if handle_transport("seed upsert", s_up, raw_up) or s_up != 200:
            print("SETUP_ERROR: seed upsert failed")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        s_ct, raw_ct = safe_request("POST", "count", path_params={"name": C},
                                    body={"exact": True})
        print(f"[seed count] status={s_ct} raw={str(raw_ct)[:160]}")
        if handle_transport("count", s_ct, raw_ct) or s_ct != 200:
            print("SETUP_ERROR: count failed")
            return "SCRIPT_ERROR"

        def paginate(run_tag):
            """Explicit-offset pagination with exact=true. Returns
            (sequence, page_sizes, npo_log) or None on hard failure."""
            seq = []
            sizes = []
            npo_log = []
            offset = 0
            while offset < N_POINTS:
                body = {"query": QUERY_VEC, "limit": LIMIT, "offset": offset,
                        "params": {"exact": True}}
                s, raw = safe_request("POST", "query",
                                      path_params={"name": C}, body=body)
                print(f"[{run_tag} offset={offset}] status={s} "
                      f"raw={str(raw)[:200]}")
                if handle_transport(f"{run_tag} offset={offset}", s, raw):
                    return None
                if s != 200:
                    DEFECTS.append(f"({run_tag} offset={offset}) exact "
                                   f"pagination returned {s} — "
                                   f"raw={str(raw)[:150]}")
                    return None
                try:
                    res = json.loads(raw).get("result")
                except (json.JSONDecodeError, ValueError, TypeError,
                        AttributeError):
                    res = None
                page = res.get("points") if isinstance(res, dict) else None
                if not isinstance(page, list):
                    DEFECTS.append(f"({run_tag} offset={offset}) 200 but "
                                   f"result.points not an array — "
                                   f"raw={str(raw)[:150]}")
                    return None
                ids = [p.get("id") for p in page if isinstance(p, dict)]
                seq.extend(ids)
                sizes.append(len(ids))
                npo_log.append(res.get("next_page_offset")
                               if isinstance(res, dict) else "no-result-obj")
                if not ids:
                    break
                offset += len(ids)
            return seq, sizes, npo_log

        run1 = paginate("E1-run1")
        if run1 is None:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND" if DEFECTS else "SCRIPT_ERROR"
        seq1, sizes1, npo1 = run1

        exp = expected_order()
        print(f"[E1] page sizes: {sizes1}")
        print(f"[E1] got     : {seq1}")
        print(f"[E1] expected: {exp}")

        # page-size arithmetic: 40 = 5*7 + 5
        exp_sizes = [LIMIT] * (N_POINTS // LIMIT)
        if N_POINTS % LIMIT:
            exp_sizes.append(N_POINTS % LIMIT)
        if sizes1 != exp_sizes:
            DEFECTS.append(f"(E1) page sizes {sizes1} != arithmetic "
                           f"{exp_sizes} for {N_POINTS} points at "
                           f"limit={LIMIT} — Type4_StateLogicViolation")
        if len(seq1) != N_POINTS:
            DEFECTS.append(f"(E1) pagination covered {len(seq1)} ids != "
                           f"{N_POINTS} seeded — loss/dup across pages — "
                           f"Type4_StateLogicViolation")
        if len(set(seq1)) != len(seq1):
            dups = sorted({x for x in seq1 if seq1.count(x) > 1})
            DEFECTS.append(f"(E1) duplicate ids across exact pages: {dups} — "
                           f"Type4_StateLogicViolation")
        if seq1 != exp:
            div = next((i for i, (a, b) in enumerate(zip(seq1, exp))
                        if a != b), min(len(seq1), len(exp)))
            DEFECTS.append(f"(E1) exact=true page order deviates from "
                           f"arithmetic descending-dot order — "
                           f"Type4_StateLogicViolation — first divergence at "
                           f"index {div}")
        else:
            print("[E1] OK: exact pagination complete, duplicate-free, "
                  "arithmetic order")

        # E3: next_page_offset presence pattern (soft oracle)
        if len(npo1) == len(exp_sizes):
            for idx, npo in enumerate(npo1):
                is_final = (idx == len(exp_sizes) - 1)
                if is_final and npo is not None:
                    WARNINGS.append(f"(E3) final page carried next_page_offset="
                                    f"{npo!r}")
                if not is_final and npo is None:
                    WARNINGS.append(f"(E3) non-final page {idx} lacked "
                                    f"next_page_offset")
        print(f"[E3] next_page_offset log: {npo1}")

        # ---- E2: identical second run must be identical (stability promise) ----
        run2 = paginate("E2-run2")
        if run2 is None:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND" if DEFECTS else "SCRIPT_ERROR"
        seq2, sizes2, _npo2 = run2
        if seq2 != seq1:
            DEFECTS.append(f"(E2) second identical exact=true pagination "
                           f"differs from the first run — documented "
                           f"stability of exact pagination violated — "
                           f"Type4_StateLogicViolation — "
                           f"run1={seq1[:10]}... run2={seq2[:10]}...")
        else:
            print("[E2] OK: run-to-run exact pagination sequence identical")

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
