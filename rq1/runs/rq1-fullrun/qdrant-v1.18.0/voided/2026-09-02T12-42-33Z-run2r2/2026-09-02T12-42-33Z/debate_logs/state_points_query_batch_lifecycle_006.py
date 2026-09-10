#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_query_batch_lifecycle_006
# strategy: lifecycle_concurrency
# endpoint: points+query+batch
# constraint_ids: qdrant_behavioral_points_query_batch_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/batch-query
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 Concurrency State Blindness
# exploration_target: novel_candidate
"""
Attack: collection lifecycle race x concurrent BATCH query (Strategy 7:
  lifecycle concurrency; Blindspot BS-03). This transplants the
  R39-CONFIRMED productive family on the single-query face ("a raced 500
  displacing a documented 404 — unhandled teardown race") onto the
  batch-query face of the same chunk family, which no prior round
  reported (novel_candidate: lifecycle endpoint x batch access face).
  Thread A runs 10 lifecycle cycles (DELETE collection -> 50ms -> PUT
  create same name -> 50ms) and guarantees a final create; thread B
  concurrently issues 40 BATCH queries (3 nearest searches each —
  nearest-only because a by-id search of a not-yet-seeded id legitimately
  4xx and would poison the disposition tally). While the collection is
  momentarily absent the CORRECT disposition is 404 (the assertion pins
  "missing collection returns 404"); a bare 404 is NOT a defect.
  Defect signals: 500/panic (Type3_RuntimeFailure) — the server must
  gracefully handle a temporarily-absent collection (qdrant #9229
  'Expected at least one response' 500 family). Reproduction rule: a 500
  counts toward DEFECT_FOUND only if it occurs >= 2 times with /healthz
  alive in the same run (sporadic single occurrence = WARN). Post-cycle
  coherence (Type4 leg): after the churn stops on a fresh create, seed 5
  points wait=true -> exact count must be 5, and a batch query
  [by-id 11, nearest] must return 200 with len(result)==2 and the by-id
  entry containing id 11 — residual state from the drop/create churn
  must not leak into the new incarnation.
  [chunk_points+query+batch coverage: lifecycle_concurrency x
  qdrant_behavioral_points_query_batch_001 (drop/create churn x batch
  query: 404-vs-500 disposition + post-cycle seed/count/by-id batch
  coherence)]
Oracle: every access-thread batch query returns 200 or 404 (200 while
  the collection exists, 404 while momentarily absent — both correct);
  >= 2 distinct 5xx with /healthz alive = Type3_RuntimeFailure (single
  5xx = WARN per the reproduction rule); post-cycle: seed of 5 points ->
  exact count == 5 (mismatch = Type4_StateLogicViolation) and batch
  [by-id 11, nearest] -> 200 with len(result)==2 and entry0 containing
  id 11 (missing = Type4); transport failure -> liveness re-check before
  any verdict (dead service = SCRIPT_ERROR).
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
      f"{[k for k in sorted(rt.PATHS) if k in ('query_batch', 'create_collection', 'drop_collection', 'upsert_points', 'count', 'healthz')]}")

DEFECTS = []
WARNINGS = []
ABORT = [False]

N_CYCLES = 10
N_ACCESS = 40

CHURN_SEARCHES = [
    {"query": [0.1, 0.2, 0.3, 0.4], "limit": 3},
    {"query": [1.0, 0.0, 0.0, 0.0], "limit": 2},
    {"query": [0.0, 1.0, 0.0, 0.0], "limit": 1},
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


def lifecycle_thread(coll, tally):
    for cycle in range(N_CYCLES):
        s_d, raw_d = safe_request("DELETE", "drop_collection",
                                  path_params={"name": coll})
        tally[f"drop_{s_d}"] = tally.get(f"drop_{s_d}", 0) + 1
        time.sleep(0.05)
        s_c, raw_c = safe_request("PUT", "create_collection",
                                  path_params={"name": coll},
                                  body={"vectors": {"size": 4,
                                                    "distance": "Cosine"}})
        tally[f"create_{s_c}"] = tally.get(f"create_{s_c}", 0) + 1
        if s_c not in (200, 201, 409):
            print(f"[lifecycle cycle {cycle}] create status={s_c} "
                  f"raw={str(raw_c)[:120]}")
        time.sleep(0.05)
    # guarantee the collection exists at the end (idempotent final create)
    s_f, raw_f = safe_request("PUT", "create_collection",
                              path_params={"name": coll},
                              body={"vectors": {"size": 4,
                                                "distance": "Cosine"}})
    tally[f"create_{s_f}"] = tally.get(f"create_{s_f}", 0) + 1
    print(f"[lifecycle] final create status={s_f}")


def access_thread(coll, tally, errors_5xx, errors_other):
    for i in range(N_ACCESS):
        s, raw = safe_request("POST", "query_batch",
                              path_params={"collection_name": coll},
                              body={"searches": CHURN_SEARCHES})
        tally[f"batch_{s}"] = tally.get(f"batch_{s}", 0) + 1
        if s == 0:
            if not liveness(f"access-it{i}"):
                ABORT[0] = True
            return
        if 500 <= s <= 599:
            errors_5xx.append((i, s, str(raw)[:120]))
            if not liveness(f"access-5xx-it{i}"):
                ABORT[0] = True
                return
        elif s not in (200, 404):
            errors_other.append((i, s, str(raw)[:120]))
        elif s == 200:
            res = result_of(raw)
            if not isinstance(res, list) or len(res) != len(CHURN_SEARCHES):
                errors_other.append((i, s, "bad result shape"))
        time.sleep(0.03)


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spqb6_" + TS + "_"
    C = PFX + "col"

    try:
        # initial create so the access thread's first queries have a target
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: initial setup_default failed: {err}")
            return "SCRIPT_ERROR"

        tally = {}
        errors_5xx = []
        errors_other = []
        t_a = threading.Thread(target=lifecycle_thread, args=(C, tally))
        t_b = threading.Thread(target=access_thread,
                               args=(C, tally, errors_5xx, errors_other))
        t0 = time.time()
        t_a.start()
        t_b.start()
        t_a.join()
        t_b.join()
        print(f"[race] finished in {time.time() - t0:.1f}s; status tally: "
              f"{dict(sorted(tally.items()))}")
        print(f"[race] 5xx events ({len(errors_5xx)}): {errors_5xx[:6]}")
        print(f"[race] other-than-200/404 events ({len(errors_other)}): "
              f"{errors_other[:6]}")

        if len(errors_5xx) >= 2:
            DEFECTS.append(f"(race) access batch query returned 5xx "
                           f"{len(errors_5xx)} times with /healthz alive "
                           f"during collection drop/create churn — should "
                           f"be graceful 404, not internal error — "
                           f"Type3_RuntimeFailure — sample={errors_5xx[:3]}")
        elif len(errors_5xx) == 1:
            WARNINGS.append(f"(race) single sporadic 5xx observed "
                            f"({errors_5xx[0]}) — below the >=2 reproduction "
                            f"threshold; printed for re-run triage")
        for (i, s, raw) in errors_other:
            if 400 <= s <= 499:
                WARNINGS.append(f"(race) access batch query it{i} returned "
                                f"{s} (404 is the specified missing-collection "
                                f"status) — raw={raw}")
            else:
                DEFECTS.append(f"(race) access batch query it{i} returned "
                               f"unexpected status {s} — raw={raw}")

        # ---- post-cycle coherence ----
        s_up, raw_up = safe_request("PUT", "upsert_points",
                                    path_params={"name": C},
                                    body={"points": [
                                        {"id": 11, "vector": [1.0, 0.0, 0.0, 0.0]},
                                        {"id": 12, "vector": [0.9, 0.1, 0.0, 0.0]},
                                        {"id": 13, "vector": [0.8, 0.2, 0.0, 0.0]},
                                        {"id": 14, "vector": [0.0, 1.0, 0.0, 0.0]},
                                        {"id": 15, "vector": [0.1, 0.9, 0.0, 0.0]},
                                    ]},
                                    query_params={"wait": "true"})
        print(f"[post-cycle seed] status={s_up} raw={str(raw_up)[:160]}")
        if s_up == 0 or 500 <= s_up <= 599:
            if not handle_post_cycle_transport("post-seed", s_up, raw_up):
                return "SCRIPT_ERROR"
            if 500 <= s_up <= 599:
                for d in DEFECTS:
                    print(f"DEFECT: {d}")
                return "DEFECT_FOUND"   # 5xx with service alive recorded
        elif s_up != 200:
            print(f"SETUP_ERROR: post-cycle seed returned {s_up}")
            return "SCRIPT_ERROR"

        s_ct, raw_ct = safe_request("POST", "count", path_params={"name": C},
                                    body={"exact": True})
        print(f"[post-cycle count] status={s_ct} raw={str(raw_ct)[:160]}")
        if s_ct == 200:
            res = result_of(raw_ct)
            cnt = res.get("count") if isinstance(res, dict) else None
            if isinstance(cnt, int) and cnt != 5:
                DEFECTS.append(f"(post-cycle) exact count {cnt} != 5 seeded "
                               f"after lifecycle churn — residual/lost state "
                               f"— Type4_StateLogicViolation")
            elif isinstance(cnt, int):
                print("[post-cycle] OK: count == 5")
        elif s_ct == 0 or 500 <= s_ct <= 599:
            if not handle_post_cycle_transport("post-count", s_ct, raw_ct):
                return "SCRIPT_ERROR"
            if 500 <= s_ct <= 599:
                for d in DEFECTS:
                    print(f"DEFECT: {d}")
                return "DEFECT_FOUND"

        s_q, raw_q = safe_request("POST", "query_batch",
                                  path_params={"collection_name": C},
                                  body={"searches": [
                                      {"query": 11, "limit": 3},
                                      {"query": [0.1, 0.2, 0.3, 0.4],
                                       "limit": 2},
                                  ]})
        print(f"[post-cycle batch by-id 11] status={s_q} "
              f"raw={str(raw_q)[:260]}")
        if s_q == 0 or 500 <= s_q <= 599:
            handle_post_cycle_transport("post-byid", s_q, raw_q)
        elif s_q == 200:
            res = result_of(raw_q)
            if not isinstance(res, list) or len(res) != 2:
                DEFECTS.append("(post-cycle) batch [by-id 11, nearest] "
                               "returned 200 but not a 2-entry result array "
                               "— Type4_StateLogicViolation")
            else:
                entry0 = res[0]
                pts = entry0.get("points") if isinstance(entry0, dict) else None
                ids = [p.get("id") for p in (pts or [])
                       if isinstance(p, dict) and "id" in p]
                if 11 not in ids:
                    DEFECTS.append(f"(post-cycle) by-id entry for seeded id "
                                   f"11 returned ids {ids} — incoherent "
                                   f"fresh state — Type4_StateLogicViolation")
                else:
                    print("[post-cycle] OK: batch by-id query works on "
                          "fresh state")
        else:
            DEFECTS.append(f"(post-cycle) batch query on recreated+seeded "
                           f"collection returned {s_q} — "
                           f"Type4_StateLogicViolation")

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


def handle_post_cycle_transport(tag, status, raw):
    if status == 0:
        if not liveness(tag):
            ABORT[0] = True
        return False
    if 500 <= status <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) returned {status} with service alive — "
                           f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
            return True
        ABORT[0] = True
        return False
    return True


if __name__ == "__main__":
    try:
        _v = main()
    except Exception:
        import traceback
        traceback.print_exc()
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
