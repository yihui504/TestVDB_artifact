#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_recommend_concurrent_005
# strategy: concurrent
# endpoint: points+recommend
# constraint_ids: qdrant_behavioral_points_recommend_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/search/recommend-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: recommend readers racing point deletes (Strategy 4:
  concurrent-operation attack; Blindspot BS-03 Concurrency State
  Blindness) x qdrant_behavioral_points_recommend_001. The recommend
  fetch path dereferences the CURRENT state of every referenced id; a
  reference id that is being deleted concurrently makes the request
  legality time-dependent. The graceful-degradation contract: every
  reader response must be either 200 (reference still present at fetch
  time, well-formed result array) or a 4xx client error (reference
  already gone) — NEVER a 5xx internal error and never a 200 with a
  malformed body (result-completeness guard). This measures the
  recommend face's guard status, which the R39/R40 teardown-race
  family left unmeasured (single face 404/500, batch face
  malformed-200). Legs:
  (P) seed ids 101..124 (24 pts); count==24.
  (race) 1 deleter thread deletes ids 101..112 one-by-one (wait=true,
  20ms gap) while N reader threads (TESTVDB_CONCURRENT_THREADS,
  default 10, capped at 20) each issue 12 recommends whose positive
  reference rotates over the ids being deleted.
  (post) after join: exact count == 12 (24-12 arithmetic);
  recommend(positive=[101]) -> 4xx strict (deleted reference);
  recommend(positive=[113]) -> 200 strict (survivor reference);
  /healthz alive.
  Mutation-point justification (G6): deleting exactly the ids the
  readers dereference, concurrently with the reads, is the maximal
  timing pressure on the fetch-then-search path — the window where a
  shard's point state flips between fetch and use is where the
  confirmed 500/malformed-200 race family lives (qdrant #9229 analog
  at point level).
  [chunk_points+recommend coverage: concurrent x
  qdrant_behavioral_points_recommend_001 (reader-vs-delete race: no
  5xx, no malformed 200 during race + post-race count arithmetic +
  post-race strict 4xx/200 dispositions)]
Oracle: during the race every reader response is 200 (result is an
  array) or 4xx — any 5xx with /healthz alive = Type3_RuntimeFailure;
  any 200 whose result is not an array = result-completeness
  violation (Type4_StateLogicViolation); post-race exact count == 12
  (mismatch = Type4); recommend(positive=[deleted 101]) -> 4xx (200 =
  ghost reference, Type4); recommend(positive=[survivor 113]) -> 200
  non-empty (4xx = over-deletion on the read path, Type4); final
  /healthz == 200 else SCRIPT_ERROR. Single VERDICT line aggregates
  all threads.
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
    return s, [p.get("id") for p in res if isinstance(p, dict)]


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spr5_" + TS + "_"
    C = PFX + "col"
    DIM = 4
    DOOMED = list(range(101, 113))    # ids the deleter removes
    SURVIVORS = list(range(113, 125))  # ids never touched

    try:
        _t = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10"))
        THREADS = max(2, min(20, _t))
    except ValueError:
        THREADS = 10
    print(f"[config] reader threads={THREADS} (TESTVDB_CONCURRENT_THREADS)")

    def vec(i):
        return [1.0, 0.02 * (i % 50), 0.0, 0.0]

    try:
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        if not upsert(C, [{"id": i, "vector": vec(i)}
                          for i in DOOMED + SURVIVORS]):
            print("SETUP_ERROR: seed upsert failed")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if exact_count("seed", C) != len(DOOMED) + len(SURVIVORS):
            print("SETUP_ERROR: seed count != 24")
            return "SCRIPT_ERROR"

        # baseline sanity before the race (deterministic 200)
        s_base, ids_base = recommend("base-ref101", C,
                                     {"positive": [101], "limit": 3})
        if s_base != 200 or ids_base is None:
            print("SETUP_ERROR: baseline recommend not 200")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"

        race_anomalies = []   # per-thread collected anomalies
        race_counts = {"200": 0, "4xx": 0}
        race_lock = threading.Lock()

        def deleter():
            for pid in DOOMED:
                s, raw = safe_request("POST", "delete_points",
                                      path_params={"name": C},
                                      body={"points": [pid]},
                                      query_params={"wait": "true"})
                if handle_transport(f"deleter-{pid}", s, raw):
                    return
                if s != 200:
                    with race_lock:
                        race_anomalies.append(
                            f"deleter: delete of {pid} returned {s} — "
                            f"raw={str(raw)[:120]}")
                time.sleep(0.02)

        def reader(tid):
            anomalies = []
            local = {"200": 0, "4xx": 0}
            for it in range(12):
                ref = DOOMED[(tid * 7 + it) % len(DOOMED)]
                s, raw = safe_request("POST", "recommend",
                                      path_params={"name": C},
                                      body={"positive": [ref], "limit": 3},
                                      timeout=20)
                if handle_transport(f"reader{tid}-it{it}", s, raw):
                    return
                if s == 200:
                    res = result_of(raw)
                    if not isinstance(res, list):
                        anomalies.append(
                            f"reader{tid} it{it}: 200 but result not an "
                            f"array — result-completeness guard absent — "
                            f"raw={str(raw)[:150]}")
                    local["200"] += 1
                elif 400 <= s <= 499:
                    local["4xx"] += 1  # legal: reference already deleted
                else:
                    anomalies.append(
                        f"reader{tid} it{it}: unexpected status {s} — "
                        f"raw={str(raw)[:150]}")
            with race_lock:
                race_anomalies.extend(anomalies)
                race_counts["200"] += local["200"]
                race_counts["4xx"] += local["4xx"]

        threads = [threading.Thread(target=deleter, name="deleter")]
        for tid in range(THREADS):
            threads.append(threading.Thread(target=reader, args=(tid,),
                                            name=f"reader-{tid}"))
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        print(f"[race] reader outcomes: 200={race_counts['200']} "
              f"4xx={race_counts['4xx']} anomalies={len(race_anomalies)}")
        for a in race_anomalies:
            DEFECTS.append(f"({a.split(':')[0]}) race anomaly: {a}")

        # ---- post-race: deterministic strict checks ----
        time.sleep(0.5)
        cnt = exact_count("post-race", C)
        if cnt is not None and cnt != len(SURVIVORS):
            DEFECTS.append(f"(post) exact count {cnt} != 24-12=12 after the "
                           f"race — concurrent delete lost/duplicated points — "
                           f"Type4_StateLogicViolation")
        else:
            print("[post] OK: count 24->12 arithmetic holds")

        s_pd, ids_pd = recommend("post-deleted-101", C,
                                 {"positive": [101], "limit": 3})
        if s_pd == 200:
            DEFECTS.append(f"(post) recommend positive=[deleted 101] returned "
                           f"200 with ids={ids_pd} — ghost reference after "
                           f"race — Type4_StateLogicViolation")
        elif s_pd is not None and s_pd > 0 and not (400 <= s_pd <= 499):
            DEFECTS.append(f"(post) recommend positive=[deleted 101] returned "
                           f"unexpected status {s_pd} — raw check needed")
        else:
            print(f"[post] OK: deleted reference rejected with {s_pd}")

        s_ps, ids_ps = recommend("post-survivor-113", C,
                                 {"positive": [113], "limit": 3})
        if s_ps != 200:
            if s_ps is not None and s_ps > 0 and 400 <= s_ps <= 499:
                DEFECTS.append(f"(post) recommend positive=[survivor 113] "
                               f"rejected with {s_ps} after a race that never "
                               f"touched 113 — over-deletion on the read path "
                               f"— Type4_StateLogicViolation")
            elif s_ps is not None and s_ps > 0:
                print(f"[post] note: survivor reference got status {s_ps}")
        else:
            if not ids_ps:
                DEFECTS.append("(post) survivor recommend 200 with EMPTY "
                               "result — Type4_StateLogicViolation")
            else:
                print(f"[post] OK: survivor reference returned ids={ids_ps}")

        if not liveness("final"):
            ABORT[0] = True

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
