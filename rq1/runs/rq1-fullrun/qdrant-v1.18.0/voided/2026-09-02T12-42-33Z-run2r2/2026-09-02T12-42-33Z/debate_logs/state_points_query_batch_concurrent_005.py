#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_query_batch_concurrent_005
# strategy: concurrent
# endpoint: points+query+batch
# constraint_ids: qdrant_behavioral_points_query_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/batch-query
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 Concurrency State Blindness
"""
Attack: batch-query consistency under concurrent point writes (Strategy
  4: concurrent-operation attack; Blindspot BS-03) x
  qdrant_behavioral_points_query_batch_001 ("HTTP 200 with one result
  per search"). The collection EXISTS for the whole run (no lifecycle
  churn — that is script _006), so every reader batch query is a valid
  request against an existing collection and the pinned 200 disposition
  holds throughout. Writer threads upsert disjoint id ranges with
  wait=true (deterministic settle); reader threads continuously fire
  4-search batches (nearest-only: by-id searches of ids not yet written
  would legitimately 4xx mid-run and poison the disposition tally).
  Judge:
  (R1) every reader batch -> 200 with len(result)==4 and each entry an
  object with a points list (response_shape). 5xx >= 2 occurrences with
  /healthz alive = Type3_RuntimeFailure (single = WARN, race false-
  positive rule); 4xx >= 2 = Type4 (violates the pinned 200-on-valid);
  single 4xx = WARN (mid-write dispositions on a read face are benign
  territory — R35).
  (R2) after all writers settle: exact count must equal seed + written
  (count consistency under concurrency, supports
  qdrant_inv_count_consistency_001); a settling poll (<=5 x 1s) absorbs
  residual propagation before judging.
  (R3) a final batch query post-settle -> 200 len==4.
  Thread counts honor TESTVDB_CONCURRENT_THREADS (default 10):
  writers = clamp(THREADS//2, 2, 8), readers = clamp(THREADS//5, 1, 4).
  [chunk_points+query+batch coverage: concurrent x
  qdrant_behavioral_points_query_batch_001 (concurrent upserts x batch
  queries: per-search result integrity during writes + settled count
  arithmetic + post-settle batch health)]
Oracle: all reader batch queries return 200 with len(result)==4 and
  per-entry points lists (>=2 5xx with /healthz alive =
  Type3_RuntimeFailure; >=2 4xx = Type4_StateLogicViolation against the
  pinned 200; single occurrences = WARN per the reproduction rule);
  settled exact count == 20 + 3*25*writers (mismatch =
  Type4_StateLogicViolation); post-settle batch -> 200 len==4;
  transport failure -> liveness re-check before any verdict (dead
  service = SCRIPT_ERROR).
"""

import os
import sys
import json
import time
import threading
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
#   {"path": "points+query+batch", "method": "POST",
#    "url": "/collections/{collection_name}/points/query/batch"}
rt.PATHS["query_batch"] = "/collections/{collection_name}/points/query/batch"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if k in ('query_batch', 'upsert_points', 'count', 'healthz')]}")

DEFECTS = []
WARNINGS = []
ABORT = [False]

THREADS = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10") or "10")
N_WRITERS = max(2, min(8, THREADS // 2))
N_READERS = max(1, min(4, THREADS // 5))
N_SEED = 20
WRITER_REQUESTS = 25
WRITER_BATCH = 3
N_READER_ITERS = 20

READER_SEARCHES = [
    {"query": [1.0, 0.0, 0.0, 0.0], "limit": 3},
    {"query": [0.0, 1.0, 0.0, 0.0], "limit": 2},
    {"query": [0.0, 0.0, 1.0, 0.0], "limit": 1},
    {"query": [0.7, 0.7, 0.0, 0.0], "limit": 4},
]


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


def writer_thread(coll, wid, tally):
    base = 10000 + wid * 10000
    for r in range(WRITER_REQUESTS):
        pts = []
        for k in range(WRITER_BATCH):
            pid = base + r * WRITER_BATCH + k
            v = [0.0] * 4
            v[(pid + wid) % 4] = 1.0
            pts.append({"id": pid, "vector": v})
        s, raw = safe_request("PUT", "upsert_points",
                              path_params={"name": coll},
                              body={"points": pts},
                              query_params={"wait": "true"})
        tally[f"upsert_{s}"] = tally.get(f"upsert_{s}", 0) + 1
        if s == 0:
            if not liveness(f"writer{wid}-it{r}"):
                ABORT[0] = True
            return
        if 500 <= s <= 599:
            if not liveness(f"writer{wid}-5xx-it{r}"):
                ABORT[0] = True
                return
            DEFECTS.append(f"(writer{wid}) upsert returned {s} with service "
                           f"alive — Type3_RuntimeFailure — "
                           f"raw={str(raw)[:120]}")
            return
        time.sleep(0.01)


def reader_thread(coll, rid, tally, err_5xx, err_4xx, err_shape):
    for it in range(N_READER_ITERS):
        s, raw = safe_request("POST", "query_batch",
                              path_params={"collection_name": coll},
                              body={"searches": READER_SEARCHES})
        tally[f"batch_{s}"] = tally.get(f"batch_{s}", 0) + 1
        if s == 0:
            if not liveness(f"reader{rid}-it{it}"):
                ABORT[0] = True
            return
        if 500 <= s <= 599:
            err_5xx.append((rid, it, s, str(raw)[:100]))
            if not liveness(f"reader{rid}-5xx-it{it}"):
                ABORT[0] = True
                return
        elif 400 <= s <= 499:
            err_4xx.append((rid, it, s, str(raw)[:100]))
        elif s == 200:
            res = result_of(raw)
            if not isinstance(res, list) or len(res) != len(READER_SEARCHES):
                err_shape.append((rid, it, f"len={len(res) if isinstance(res, list) else 'non-list'}"))
            else:
                for i, entry in enumerate(res):
                    if not isinstance(entry, dict) or not isinstance(
                            entry.get("points"), list):
                        err_shape.append((rid, it, f"entry{i}-shape"))
        time.sleep(0.02)


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spqb5_" + TS + "_"
    C = PFX + "col"
    expected_total = N_SEED + N_WRITERS * WRITER_REQUESTS * WRITER_BATCH
    print(f"[plan] writers={N_WRITERS} readers={N_READERS} "
          f"expected_total={expected_total}")

    try:
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"

        seed = []
        for i in range(1, N_SEED + 1):
            v = [0.0] * 4
            v[i % 4] = 1.0
            seed.append({"id": i, "vector": v})
        s, raw = safe_request("PUT", "upsert_points",
                              path_params={"name": C},
                              body={"points": seed},
                              query_params={"wait": "true"})
        print(f"[seed] status={s} raw={str(raw)[:180]}")
        if s == 0 or 500 <= s <= 599:
            if s == 0 and not liveness("seed"):
                return "SCRIPT_ERROR"
            if 500 <= s <= 599 and liveness("seed"):
                DEFECTS.append(f"(seed) upsert returned {s} with service "
                               f"alive — Type3_RuntimeFailure")
                return "DEFECT_FOUND"
            return "SCRIPT_ERROR"
        if s != 200:
            print(f"SETUP_ERROR: seed upsert returned {s}")
            return "SCRIPT_ERROR"

        tally = {}
        err_5xx, err_4xx, err_shape = [], [], []
        threads = []
        for w in range(N_WRITERS):
            t = threading.Thread(target=writer_thread, args=(C, w, tally))
            threads.append(t)
        for r in range(N_READERS):
            t = threading.Thread(target=reader_thread,
                                 args=(C, r, tally, err_5xx, err_4xx, err_shape))
            threads.append(t)
        t0 = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        print(f"[race] finished in {time.time() - t0:.1f}s; tally: "
              f"{dict(sorted(tally.items()))}")
        print(f"[race] reader 5xx ({len(err_5xx)}): {err_5xx[:5]}")
        print(f"[race] reader 4xx ({len(err_4xx)}): {err_4xx[:5]}")
        print(f"[race] reader shape errors ({len(err_shape)}): {err_shape[:5]}")

        # (R1) disposition + integrity rules
        if len(err_5xx) >= 2:
            DEFECTS.append(f"(R1) reader batch queries returned 5xx "
                           f"{len(err_5xx)} times with /healthz alive during "
                           f"pure write concurrency — collection existed "
                           f"throughout, the pinned disposition is 200 — "
                           f"Type3_RuntimeFailure — sample={err_5xx[:3]}")
        elif len(err_5xx) == 1:
            WARNINGS.append(f"(R1) single sporadic 5xx ({err_5xx[0]}) — "
                            f"below the >=2 reproduction threshold")
        if len(err_4xx) >= 2:
            DEFECTS.append(f"(R1) reader batch queries returned 4xx "
                           f"{len(err_4xx)} times during pure write "
                           f"concurrency (collection existed, searches "
                           f"valid) — violates the pinned 200-on-valid — "
                           f"Type4_StateLogicViolation — sample={err_4xx[:3]}")
        elif len(err_4xx) == 1:
            WARNINGS.append(f"(R1) single 4xx on a valid batch during "
                            f"writes ({err_4xx[0]}) — below the >=2 "
                            f"threshold; read faces are benign territory "
                            f"(R35)")
        if err_shape:
            DEFECTS.append(f"(R1) {len(err_shape)} 200-responses violated "
                           f"the per-search integrity (len(result)==4, "
                           f"entries with points lists) — "
                           f"Type4_StateLogicViolation — sample="
                           f"{err_shape[:3]}")

        # (R2) settled count arithmetic (poll <= 5 x 1s)
        cnt = None
        for attempt in range(5):
            s_ct, raw_ct = safe_request("POST", "count",
                                        path_params={"name": C},
                                        body={"exact": True})
            print(f"[settle count try{attempt}] status={s_ct} "
                  f"raw={str(raw_ct)[:160]}")
            if s_ct == 0 or 500 <= s_ct <= 599:
                if s_ct == 0 and not liveness("settle-count"):
                    return "SCRIPT_ERROR"
                if 500 <= s_ct <= 599 and liveness("settle-count"):
                    DEFECTS.append(f"(R2) count returned {s_ct} with service "
                                   f"alive — Type3_RuntimeFailure")
                    break
                return "SCRIPT_ERROR"
            if s_ct != 200:
                print(f"SETUP_ERROR: count returned {s_ct}")
                return "SCRIPT_ERROR"
            res = result_of(raw_ct)
            cnt = res.get("count") if isinstance(res, dict) else None
            if isinstance(cnt, int) and cnt == expected_total:
                break
            time.sleep(1.0)
        if isinstance(cnt, int) and cnt != expected_total:
            DEFECTS.append(f"(R2) settled exact count {cnt} != expected "
                           f"{expected_total} (seed {N_SEED} + "
                           f"{N_WRITERS}x{WRITER_REQUESTS}x{WRITER_BATCH} "
                           f"wait=true writes) — lost/duplicated writes — "
                           f"Type4_StateLogicViolation")
        elif isinstance(cnt, int):
            print(f"[R2] OK: settled count == {expected_total}")

        # (R3) post-settle batch health
        s, raw = safe_request("POST", "query_batch",
                              path_params={"collection_name": C},
                              body={"searches": READER_SEARCHES})
        print(f"[R3 post-settle batch] status={s} raw={str(raw)[:240]}")
        if s == 0:
            if not liveness("R3"):
                ABORT[0] = True
        elif 500 <= s <= 599:
            if liveness("R3"):
                DEFECTS.append(f"(R3) post-settle batch returned {s} with "
                               f"service alive — Type3_RuntimeFailure")
            else:
                ABORT[0] = True
        elif s != 200:
            DEFECTS.append(f"(R3) post-settle batch returned {s} — "
                           f"assertion pins 200 — "
                           f"Type4_StateLogicViolation")
        else:
            res = result_of(raw)
            if not isinstance(res, list) or len(res) != len(READER_SEARCHES):
                DEFECTS.append("(R3) post-settle 200 result is not a "
                               f"{len(READER_SEARCHES)}-entry array — "
                               "Type4_StateLogicViolation")

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
