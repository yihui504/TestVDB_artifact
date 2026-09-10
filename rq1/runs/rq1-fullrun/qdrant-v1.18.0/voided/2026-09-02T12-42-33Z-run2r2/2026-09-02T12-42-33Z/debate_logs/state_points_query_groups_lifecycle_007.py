#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_points_query_groups_lifecycle_007
# strategy: lifecycle_concurrency (BS-03; R39/R40 teardown-race family, groups face)
# endpoint: points+query+groups
# constraint_ids: qdrant_behavioral_points_query_groups_001, qdrant_state_points_query_groups_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/query/query-points-groups
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: collection lifecycle churn x concurrent groups query
  (Strategy 7; Blindspot BS-03) x qdrant_behavioral_points_query_groups_001
  ("404 for a missing collection" / 200 groups shape). This extends the
  confirmed R39/R40 teardown-race family to the query/groups face: thread
  A runs 10 lifecycle cycles (DELETE collection -> 50ms -> PUT create
  same name -> 50ms) and guarantees a final create; thread B issues 40
  groups queries throughout. During churn the legal dispositions are:
  404 (collection momentarily absent), 400 (collection freshly recreated
  without the payload index — index precondition, R40 ORDER_BY analog),
  or 200 with an EMPTY but well-formed result.groups (freshly recreated,
  empty collection). Illegal: 500/panic (Type3 — the server must
  gracefully handle a temporarily-absent collection, qdrant #9229
  family) and malformed-200 — 200 whose result.groups is missing or not
  an array (Type4 result-completeness guard: the R40 batch-face lesson —
  a face lacking this guard returned structurally broken 200s under
  churn). Post-cycle coherence: after the churn settles on a fresh
  create, re-create the index, seed a 4x3 partition (wait=true) and
  demand the exact partition + count 12 — residual state from the churn
  must not leak into the new incarnation.
  [chunk_points+query+groups coverage: lifecycle_concurrency x
  qdrant_behavioral_points_query_groups_001 (+ offset-free body per
  qdrant_state_points_query_groups_001) — churn-vs-groups-query
  dispositions 404/400/empty-200 legal, 500/malformed-200 defects,
  post-cycle partition coherence]
Oracle: every access-thread groups query returns 404, 400 or a 200
  whose result.groups is a well-formed array (empty allowed); >= 2
  distinct 5xx with /healthz alive = Type3_RuntimeFailure (single 5xx =
  WARN per the reproduction rule); any malformed 200 (result.groups
  missing / not an array / entry without id+hits) = Type4_
  StateLogicViolation; post-cycle: exact count == 12 and groups query
  returns the exact seeded 4x3 partition (mismatch = Type4); transport
  failure -> /healthz liveness re-check before any verdict (dead service
  = SCRIPT_ERROR).
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
      f"{[k for k in sorted(rt.PATHS) if k in ('query_groups', 'upsert_points', 'count', 'create_index', 'create_collection', 'drop_collection', 'healthz')]}")

DEFECTS = []
WARNINGS = []
ABORT = [False]

N_CYCLES = 10
N_ACCESS = 40
GROUPS = ["g1", "g2", "g3", "g4"]
POINT_MAP = {g: [(gi + 1) * 10 + j for j in (1, 2, 3)]
             for gi, g in enumerate(GROUPS)}


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
    print(f"[liveness {tag}] healthz probe required")
    _hs, _hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={_hs} raw={str(_hraw)[:120]}")
    return _hs == 200


def groups_body():
    # offset-free body per qdrant_state_points_query_groups_001
    return {"query": [1.0, 1.0, 1.0, 1.0], "group_by": "grp",
            "limit": 5, "group_size": 2}


def lifecycle_thread(coll, tally):
    for cycle in range(N_CYCLES):
        s_d, raw_d = safe_request("DELETE", "drop_collection",
                                  path_params={"name": coll})
        tally[f"drop_{s_d}"] = tally.get(f"drop_{s_d}", 0) + 1
        time.sleep(0.05)
        s_c, raw_c = safe_request("PUT", "create_collection",
                                  path_params={"name": coll},
                                  body={"vectors": {"size": 4, "distance": "Cosine"}})
        tally[f"create_{s_c}"] = tally.get(f"create_{s_c}", 0) + 1
        if s_c not in (200, 201, 409):
            print(f"[lifecycle cycle {cycle}] create status={s_c} raw={str(raw_c)[:120]}")
        time.sleep(0.05)
    s_f, raw_f = safe_request("PUT", "create_collection",
                              path_params={"name": coll},
                              body={"vectors": {"size": 4, "distance": "Cosine"}})
    tally[f"create_{s_f}"] = tally.get(f"create_{s_f}", 0) + 1
    print(f"[lifecycle] final create status={s_f}")


def check_200_shape(raw, tag):
    """Malformed-200 guard (R40 result-completeness lesson)."""
    try:
        body = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        body = None
    if not isinstance(body, dict):
        DEFECTS.append(f"({tag}) 200 with unparseable body during lifecycle "
                       f"churn — malformed-200 — Type4_StateLogicViolation — "
                       f"raw={str(raw)[:150]}")
        return
    res = body.get("result")
    if not isinstance(res, dict) or not isinstance(res.get("groups"), list):
        DEFECTS.append(f"({tag}) 200 but result.groups missing or not an array "
                       f"during lifecycle churn — result-completeness violation "
                       f"(R40 batch-face lesson) — Type4_StateLogicViolation — "
                       f"raw={str(raw)[:150]}")
        return
    for g in res["groups"]:
        if not isinstance(g, dict) or "id" not in g or not isinstance(g.get("hits"), list):
            DEFECTS.append(f"({tag}) 200 group entry lacks id/hits during churn — "
                           f"malformed-200 — Type4_StateLogicViolation — "
                           f"entry={str(g)[:120]}")
            return


def access_thread(coll, tally, errors_5xx, errors_other):
    for i in range(N_ACCESS):
        s, raw = safe_request("POST", "query_groups", path_params={"name": coll},
                              body=groups_body())
        tally[f"groups_{s}"] = tally.get(f"groups_{s}", 0) + 1
        if s == 0:
            if not liveness(f"access-it{i}"):
                ABORT[0] = True
            return
        if 500 <= s <= 599:
            errors_5xx.append((i, s, str(raw)[:120]))
            if not liveness(f"access-5xx-it{i}"):
                ABORT[0] = True
                return
        elif s == 200:
            check_200_shape(raw, f"access-it{i}")
        elif s in (404, 400, 422):
            pass  # legal churn dispositions (absent / index precondition)
        else:
            errors_other.append((i, s, str(raw)[:120]))
        time.sleep(0.03)


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    C = "spqg7_" + TS + "_col"

    try:
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
        print(f"[race] finished in {time.time()-t0:.1f}s; tally={dict(sorted(tally.items()))}")
        print(f"[race] 5xx events ({len(errors_5xx)}): {errors_5xx[:6]}")
        print(f"[race] other unexpected ({len(errors_other)}): {errors_other[:6]}")

        if len(errors_5xx) >= 2:
            DEFECTS.append(f"(race) groups query returned 5xx {len(errors_5xx)} "
                           f"times with /healthz alive during drop/create churn — "
                           "should be graceful 404/400, not internal error — "
                           f"Type3_RuntimeFailure — sample={errors_5xx[:3]}")
        elif len(errors_5xx) == 1:
            WARNINGS.append(f"(race) single sporadic 5xx ({errors_5xx[0]}) — below "
                            f"the >=2 reproduction threshold; printed for re-run triage")
        for (i, s, raw) in errors_other:
            WARNINGS.append(f"(race) access it{i} returned unexpected {s} — "
                            f"raw={raw}")

        # ---- post-cycle coherence on the fresh incarnation ----
        s_ix, raw_ix = safe_request("PUT", "create_index", path_params={"name": C},
                                    body={"field_name": "grp",
                                          "field_schema": "keyword"},
                                    query_params={"wait": "true"})
        print(f"[post-cycle index] status={s_ix} raw={str(raw_ix)[:140]}")
        if s_ix not in (200, 201):
            print("SETUP_ERROR: post-cycle index create failed")
            return "SCRIPT_ERROR"
        pts = [{"id": pid,
                "vector": [float(pid % 7 + 1), 1.0, 0.5, float((pid % 2) + 1)],
                "payload": {"grp": g}}
               for g, ids in POINT_MAP.items() for pid in ids]
        s_up, raw_up = safe_request("PUT", "upsert_points", path_params={"name": C},
                                    body={"points": pts},
                                    query_params={"wait": "true"})
        print(f"[post-cycle seed] status={s_up} raw={str(raw_up)[:160]}")
        if s_up not in (200, 201):
            print("SETUP_ERROR: post-cycle seed failed")
            return "SCRIPT_ERROR"
        time.sleep(1)

        s_ct, raw_ct = safe_request("POST", "count", path_params={"name": C},
                                    body={"exact": True})
        print(f"[post-cycle count] status={s_ct} raw={str(raw_ct)[:160]}")
        if s_ct == 200:
            try:
                cnt = json.loads(raw_ct).get("result", {}).get("count")
            except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
                cnt = None
            if isinstance(cnt, int) and cnt != 12:
                DEFECTS.append(f"(post-cycle) exact count {cnt} != 12 on the fresh "
                               f"incarnation after churn — residual/lost state — "
                               f"Type4_StateLogicViolation")

        s_g, raw_g = safe_request("POST", "query_groups", path_params={"name": C},
                                  body={"query": [1.0, 1.0, 1.0, 1.0],
                                        "group_by": "grp", "limit": 10,
                                        "group_size": 3,
                                        "params": {"exact": True}})
        print(f"[post-cycle groups] status={s_g} raw={str(raw_g)[:260]}")
        if s_g == 0 or 500 <= s_g <= 599:
            if s_g == 0 and not liveness("post-cycle-groups"):
                return "SCRIPT_ERROR"
            if 500 <= s_g <= 599:
                if liveness("post-cycle-groups"):
                    DEFECTS.append(f"(post-cycle) groups query on freshly seeded "
                                   f"collection returned {s_g} — "
                                   f"Type3_RuntimeFailure — raw={str(raw_g)[:150]}")
                    return verdict()
                return "SCRIPT_ERROR"
        elif s_g == 200:
            check_200_shape(raw_g, "post-cycle-groups")
            try:
                gs = json.loads(raw_g).get("result", {}).get("groups", [])
                part = {str(g.get("id")): sorted(h.get("id") for h in g.get("hits", [])
                                                 if isinstance(h, dict)) for g in gs}
            except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
                part = None
            expected = {g: sorted(POINT_MAP[g]) for g in GROUPS}
            print(f"[post-cycle partition] {part}")
            if part != expected:
                DEFECTS.append(f"(post-cycle) partition {part} != seeded {expected} "
                               f"on the fresh incarnation — residual churn state — "
                               f"Type4_StateLogicViolation")
            else:
                print("[post-cycle] OK: exact 4x3 partition after churn")
        else:
            WARNINGS.append(f"(post-cycle) groups query returned {s_g} — "
                            f"raw={str(raw_g)[:120]}")

        return verdict()
    finally:
        try:
            rt.drop_collection(C)
        except Exception:
            pass


def verdict():
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


if __name__ == "__main__":
    try:
        _v = main()
    except Exception:
        import traceback
        traceback.print_exc()
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
