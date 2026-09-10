#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_query_lifecycle_008
# strategy: lifecycle_concurrency
# endpoint: points+query
# constraint_ids: qdrant_behavioral_points_query_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: collection lifecycle race x concurrent query (Strategy 7:
  lifecycle concurrency; Pattern B lifecycle; Blindspot: BS-03) x
  qdrant_behavioral_points_query_001 ("404 when the collection is
  missing"). Thread A runs 10 lifecycle cycles (DELETE collection ->
  50ms -> PUT create same name -> 50ms), then guarantees a final create;
  thread B concurrently issues 40 nearest queries against the name.
  While the collection is momentarily absent the CORRECT disposition is
  404 (graceful "collection does not exist"); a bare 404 is NOT a defect.
  Defect signals: 500/panic (Type3_RuntimeFailure) — the server must
  gracefully handle a temporarily-absent collection (reference: qdrant
  #9229 'Expected at least one response' 500 family). Reproduction rule:
  a 500 counts toward DEFECT_FOUND only if it occurs >= 2 times with
  /healthz alive in the same run (sporadic single occurrence is printed
  as WARN to avoid race false positives). Post-cycle coherence
  (Type4 leg): after the lifecycle thread stops on a fresh create, seed
  5 points wait=true -> exact count must be 5 and a by-id query must
  return 200 — residual state from the drop/create churn must not leak
  into the new incarnation.
  [chunk_points+query coverage: lifecycle_concurrency x
  qdrant_behavioral_points_query_001 (drop/create churn x query: 404-vs-
  500 disposition + post-cycle seed/count/by-id coherence)]
Oracle: every access-thread query returns 200 or 404 (200 while the
  collection exists, 404 while momentarily absent — both correct);
  >= 2 distinct 500s with /healthz alive = Type3_RuntimeFailure
  (single 500 = WARN per the reproduction rule); post-cycle: seed of 5
  points -> exact count == 5 (mismatch = Type4_StateLogicViolation) and
  by-id query of a seeded id -> 200 non-empty; transport failure ->
  liveness re-check before any verdict (dead service = SCRIPT_ERROR).
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
      f"{[k for k in sorted(rt.PATHS) if k in ('query', 'upsert_points', 'count', 'create_collection', 'drop_collection')]}")

DEFECTS = []
WARNINGS = []
ABORT = [False]

N_CYCLES = 10
N_ACCESS = 40


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
    print(f"[liveness {tag}] healthz probe required")
    _hs, _hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={_hs} raw={str(_hraw)[:120]}")
    return _hs == 200


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
        s, raw = safe_request("POST", "query", path_params={"name": coll},
                              body={"query": [0.1, 0.2, 0.3, 0.4],
                                    "limit": 3})
        tally[f"query_{s}"] = tally.get(f"query_{s}", 0) + 1
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
        time.sleep(0.03)


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spq8_" + TS + "_"
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
            DEFECTS.append(f"(race) access query returned 5xx {len(errors_5xx)} "
                           f"times with /healthz alive during collection "
                           f"drop/create churn — should be graceful 404, not "
                           f"internal error — Type3_RuntimeFailure — "
                           f"sample={errors_5xx[:3]}")
        elif len(errors_5xx) == 1:
            WARNINGS.append(f"(race) single sporadic 5xx observed "
                            f"({errors_5xx[0]}) — below the >=2 reproduction "
                            f"threshold; printed for re-run triage")
        for (i, s, raw) in errors_other:
            if 400 <= s <= 499:
                # 4xx during churn: only 404 is the specified graceful state;
                # other 4xx recorded as observation (service unavailable
                # family can be a legal transient), not auto-defect
                WARNINGS.append(f"(race) access query it{i} returned {s} "
                                f"(404 is the specified missing-collection "
                                f"status) — raw={raw}")
            else:
                DEFECTS.append(f"(race) access query it{i} returned "
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
                return "DEFECT_FOUND"   # 5xx with service alive already recorded
        elif s_up != 200:
            print(f"SETUP_ERROR: post-cycle seed returned {s_up}")
            return "SCRIPT_ERROR"

        s_ct, raw_ct = safe_request("POST", "count", path_params={"name": C},
                                    body={"exact": True})
        print(f"[post-cycle count] status={s_ct} raw={str(raw_ct)[:160]}")
        if s_ct == 200:
            try:
                cnt = json.loads(raw_ct).get("result", {}).get("count")
            except (json.JSONDecodeError, ValueError, TypeError,
                    AttributeError):
                cnt = None
            if isinstance(cnt, int) and cnt != 5:
                DEFECTS.append(f"(post-cycle) exact count {cnt} != 5 seeded "
                               f"after lifecycle churn — residual/lost state "
                               f"— Type4_StateLogicViolation")
            elif isinstance(cnt, int):
                print("[post-cycle] OK: count == 5")

        s_q, raw_q = safe_request("POST", "query", path_params={"name": C},
                                  body={"query": 11, "limit": 3})
        print(f"[post-cycle by-id query 11] status={s_q} raw={str(raw_q)[:200]}")
        if s_q == 0 or 500 <= s_q <= 599:
            handle_post_cycle_transport("post-byid", s_q, raw_q)
        elif s_q == 200:
            try:
                res = json.loads(raw_q).get("result")
            except (json.JSONDecodeError, ValueError, TypeError,
                    AttributeError):
                res = None
            pts = res.get("points") if isinstance(res, dict) else None
            if not isinstance(pts, list) or not [p for p in (pts or [])
                                                 if isinstance(p, dict)
                                                 and p.get("id") != 11]:
                DEFECTS.append("(post-cycle) by-id query of seeded id 11 "
                               "returned 200 but no other points — incoherent "
                               "fresh state — Type4_StateLogicViolation")
            else:
                print("[post-cycle] OK: by-id query works on fresh state")
        else:
            DEFECTS.append(f"(post-cycle) by-id query on recreated+seeded "
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
