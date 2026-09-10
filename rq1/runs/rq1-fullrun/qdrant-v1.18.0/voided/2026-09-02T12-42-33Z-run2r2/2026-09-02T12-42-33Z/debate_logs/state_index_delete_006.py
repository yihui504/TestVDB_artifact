#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_index_delete_006
# strategy: concurrent
# endpoint: index+delete
# constraint_ids: qdrant_state_index_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/delete-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (index deletion churn racing the data plane)
"""
Attack: concurrent (Strategy 4/7 blend: resource-level churn vs data-plane
  access, on the payload-index resource) x qdrant_state_index_delete_001.
  One live collection (12 points, f_kw in {k0:7, k1:5}, f_kw index
  PRE-created so the first delete hits a real index); then three concurrent
  parties: thread L oscillates the index state (DELETE f_kw wait=true ->
  PUT create_index f_kw wait=true, 12 toggles - every delete is against an
  existing collection so clause A promises 200 whether or not the index
  currently exists), R reader threads (TESTVDB_CONCURRENT_THREADS, clamped
  2..6) continuously take the exact filtered count on f_kw=k0 (the writer
  only ever writes f_kw=race_new, so the expected value 7 is race-free), and
  one writer thread upserts 8 distinct new points wait=true. Rationale for
  the mutation point (G6): deletion is the destructive half of the toggle
  racing the read path exactly at the moment the filter's backing structure
  disappears - the window where a naive implementation 500s or loses the
  full-scan fallback.
  [chunk_index+delete coverage: concurrent x qdrant_state_index_delete_001
  (clause A deletes under churn must stay 200; clause B data plane -
  filtered count, baseline payloads, new writes - must be invariant under
  concurrent index deletion)]
Oracle: every lifecycle DELETE returns 200 (collection exists throughout)
  and every lifecycle CREATE returns 2xx; every reader read returns 200 with
  filtered count exactly 7 (no 404, no phantom/lost data while the index is
  being deleted underneath); every writer upsert returns 2xx; after joining,
  exact total count == 20 (12 baseline + 8 new), the baseline ids' payloads
  are deep-equal to the pre-race snapshot, and filtered count on
  f_kw=race_new == 8. Sporadic 5xx/transport: healthz-gated, reported as
  Type3 only when triggered >= 2 times (reproduction rule); a single
  occurrence is logged as a transient note. 4xx on a lifecycle delete =
  Type1_IllegalSuccess; reader 200 with count != 7 or a lost baseline
  payload = Type4_StateLogicViolation (qdrant_state_index_delete_001)
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

print(f"[PATHS] index keys present="
      f"{[k for k in ('delete_index', 'create_index', 'describe_collection', 'count', 'scroll', 'upsert_points') if k in rt.PATHS]}")

N_BASE = 12
N_K0 = 7            # ids 1..7 carry k0
N_WRITE = 8         # writer ids 1000..1007 carry race_new
TOGGLES = 12
FLT_K0 = {"must": [{"key": "f_kw", "match": {"value": "k0"}}]}
FLT_NEW = {"must": [{"key": "f_kw", "match": {"value": "race_new"}}]}


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def parse_json(raw):
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return b if isinstance(b, dict) else None


def filtered_count(collection, flt):
    """(status, count_or_None, raw) via points+count exact."""
    s, raw = safe_request("POST", "count",
                          body={"exact": True, "filter": flt},
                          path_params={"name": collection})
    if s != 200:
        return s, None, raw
    b = parse_json(raw)
    cnt = None
    if b and isinstance(b.get("result"), dict) \
            and isinstance(b["result"].get("count"), int):
        cnt = b["result"]["count"]
    return s, cnt, raw


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sidd6_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []

    try:
        n_readers = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10"))
    except ValueError:
        n_readers = 10
    n_readers = max(2, min(6, n_readers))
    print(f"plan: toggles={TOGGLES} readers={n_readers} writer_points="
          f"{N_WRITE} baseline={N_BASE} (k0={N_K0})")

    obs_lock = threading.Lock()
    violations = []      # typed rule violations (Type1/Type4)
    env_events = []      # (tag, status, raw_snip, healthz_alive)
    stop_evt = threading.Event()

    def record_env(tag, status, raw):
        """Transport/5xx branch: inline healthz liveness probe, then queue."""
        hs, hraw = safe_request("GET", "healthz", timeout=10)
        with obs_lock:
            env_events.append((tag, status, str(raw)[:140], hs == 200))
        print(f"[env {tag}] status={status} healthz={hs} raw={str(raw)[:140]}")

    try:
        # ---- setup: collection + baseline points + REAL pre-created index ----
        ok, err = rt.setup_default(C, 4)
        if not ok:
            print(f"VERDICT: SCRIPT_ERROR - setup failed: {err}")
            return "SCRIPT_ERROR"
        base_pts = [
            {"id": i,
             "vector": [0.1 + 0.01 * i, 0.2, 0.3, 0.4],
             "payload": {"f_kw": "k0" if i <= N_K0 else "k1",
                         "f_int": i}}
            for i in range(1, N_BASE + 1)
        ]
        s, raw = safe_request("PUT", "upsert_points", body={"points": base_pts},
                              path_params={"name": C},
                              query_params={"wait": "true"})
        print(f"[setup upsert] status={s} raw={str(raw)[:160]}")
        if s not in (200, 201):
            return "SCRIPT_ERROR"
        s, raw = safe_request("PUT", "create_index",
                              body={"field_name": "f_kw",
                                    "field_schema": {"type": "keyword"}},
                              path_params={"name": C},
                              query_params={"wait": "true"})
        print(f"[setup create index] status={s} raw={str(raw)[:160]}")
        if s not in (200, 201):
            return "SCRIPT_ERROR"

        # pre-race control: filtered count on k0 must be exactly N_K0
        s, cnt, raw = filtered_count(C, FLT_K0)
        print(f"[pre-race control k0] status={s} count={cnt} raw={str(raw)[:160]}")
        if s != 200 or cnt != N_K0:
            print("VERDICT: SCRIPT_ERROR - pre-race control read failed")
            return "SCRIPT_ERROR"
        # pre-race baseline payload snapshot (ids 1..N_BASE)
        s, raw = safe_request("POST", "scroll",
                              body={"limit": 100, "with_payload": True},
                              path_params={"name": C})
        print(f"[pre-race scroll] status={s} raw={str(raw)[:200]}")
        b = parse_json(raw)
        res = (b or {}).get("result") if s == 200 else None
        if not isinstance(res, dict) or not isinstance(res.get("points"), list):
            return "SCRIPT_ERROR"
        snap0 = {p["id"]: p.get("payload") for p in res["points"]
                 if isinstance(p, dict) and "id" in p}
        if len(snap0) != N_BASE:
            print(f"VERDICT: SCRIPT_ERROR - baseline snapshot size "
                  f"{len(snap0)} != {N_BASE}")
            return "SCRIPT_ERROR"

        # ---- thread L: index lifecycle churn (DELETE -> CREATE) ----
        def lifecycle():
            for it in range(1, TOGGLES + 1):
                s, raw = safe_request("DELETE", "delete_index",
                                      path_params={"name": C,
                                                   "field_name": "f_kw"},
                                      query_params={"wait": "true"})
                print(f"[L toggle {it} delete] status={s} raw={str(raw)[:140]}")
                if s in (200, 201):
                    pass
                elif s == 0 or 500 <= s <= 599:
                    record_env(f"L-delete it{it}", s, raw)
                else:
                    with obs_lock:
                        violations.append(
                            f"(L-delete it{it}) index delete on an existing "
                            f"collection returned HTTP {s} (promise: 200 "
                            f"whether or not the index exists) - "
                            f"Type1_IllegalSuccess - raw={str(raw)[:120]}")
                s, raw = safe_request("PUT", "create_index",
                                      body={"field_name": "f_kw",
                                            "field_schema":
                                                {"type": "keyword"}},
                                      path_params={"name": C},
                                      query_params={"wait": "true"})
                print(f"[L toggle {it} create] status={s} raw={str(raw)[:140]}")
                if s in (200, 201):
                    pass
                elif s == 0 or 500 <= s <= 599:
                    record_env(f"L-create it{it}", s, raw)
                else:
                    with obs_lock:
                        violations.append(
                            f"(L-create it{it}) index create returned HTTP "
                            f"{s} mid-churn - Type1_IllegalSuccess - "
                            f"raw={str(raw)[:120]}")
                time.sleep(0.05)

        # ---- reader threads: race-free invariant read (k0 count == 7) ----
        def reader(idx):
            reads = 0
            while not stop_evt.is_set():
                s, cnt, raw = filtered_count(C, FLT_K0)
                reads += 1
                if s == 200:
                    if cnt is None:
                        with obs_lock:
                            violations.append(
                                f"(reader{idx}) 200 but result.count missing/"
                                f"non-integer - Type4_StateLogicViolation - "
                                f"raw={str(raw)[:120]}")
                    elif cnt != N_K0:
                        with obs_lock:
                            violations.append(
                                f"(reader{idx}) filtered count on f_kw=k0 "
                                f"returned {cnt}, expected exactly {N_K0} "
                                f"while the index churned - "
                                f"Type4_StateLogicViolation - data "
                                f"loss/phantom under concurrent index "
                                f"deletion")
                elif s == 404:
                    with obs_lock:
                        violations.append(
                            f"(reader{idx}) 404 on a read of an existing "
                            f"collection during index churn - "
                            f"Type4_StateLogicViolation - raw={str(raw)[:120]}")
                elif s == 0 or 500 <= s <= 599:
                    record_env(f"reader{idx}", s, raw)
                else:
                    with obs_lock:
                        violations.append(
                            f"(reader{idx}) read returned HTTP {s} during "
                            f"index churn - raw={str(raw)[:120]}")
                time.sleep(0.02)
            print(f"[reader{idx}] finished after {reads} reads")

        # ---- writer thread: new points must land while the index churns ----
        def writer():
            ok_writes = 0
            for j in range(N_WRITE):
                pid = 1000 + j
                s, raw = safe_request("PUT", "upsert_points",
                                      body={"points": [
                                          {"id": pid,
                                           "vector": [0.2, 0.1, 0.4, 0.3],
                                           "payload": {"f_kw": "race_new",
                                                       "f_int": pid}}]},
                                      path_params={"name": C},
                                      query_params={"wait": "true"})
                if s in (200, 201):
                    ok_writes += 1
                elif s == 0 or 500 <= s <= 599:
                    record_env(f"writer p{pid}", s, raw)
                else:
                    with obs_lock:
                        violations.append(
                            f"(writer p{pid}) upsert rejected with HTTP {s} "
                            f"during index churn - Type1_IllegalSuccess - "
                            f"raw={str(raw)[:120]}")
                time.sleep(0.03)
            print(f"[writer] acked {ok_writes}/{N_WRITE} writes")
            return ok_writes

        w_ok = [0]

        def writer_wrap():
            w_ok[0] = writer()

        th_l = threading.Thread(target=lifecycle)
        th_r = [threading.Thread(target=reader, args=(i,))
                for i in range(n_readers)]
        th_w = threading.Thread(target=writer_wrap)
        th_l.start()
        for t in th_r:
            t.start()
        th_w.start()
        th_w.join()
        th_l.join()
        stop_evt.set()
        for t in th_r:
            t.join()

        # ---- post-race reconciliation ----
        s, raw = safe_request("POST", "count", body={"exact": True},
                              path_params={"name": C})
        print(f"[post count total] status={s} raw={str(raw)[:160]}")
        b = parse_json(raw)
        total = b["result"].get("count") if s == 200 and isinstance(
            b.get("result"), dict) else None
        if total != N_BASE + N_WRITE:
            DEFECTS.append(
                f"(count) post-race total count {total} != "
                f"{N_BASE + N_WRITE} - Type4_StateLogicViolation - points "
                f"lost/duplicated during concurrent index deletion "
                f"(qdrant_state_index_delete_001 clause B)")

        s, raw = safe_request("POST", "scroll",
                              body={"limit": 100, "with_payload": True},
                              path_params={"name": C})
        print(f"[post scroll] status={s} raw={str(raw)[:200]}")
        b = parse_json(raw)
        res = (b or {}).get("result") if s == 200 else None
        if isinstance(res, dict) and isinstance(res.get("points"), list):
            snap1 = {p["id"]: p.get("payload") for p in res["points"]
                     if isinstance(p, dict) and "id" in p}
            drifted = [pid for pid in snap0
                       if snap1.get(pid) != snap0[pid]]
            missing = [pid for pid in snap0 if pid not in snap1]
            if drifted or missing:
                DEFECTS.append(
                    f"(payload) baseline data changed during index churn: "
                    f"missing={sorted(missing)[:8]} mutated={sorted(drifted)[:8]}"
                    f" - Type4_StateLogicViolation")
        else:
            print("NOTE: post-race scroll not parseable; payload "
                  "reconciliation skipped")

        s, cnt_new, raw = filtered_count(C, FLT_NEW)
        print(f"[post filtered race_new] status={s} count={cnt_new} "
              f"raw={str(raw)[:160]}")
        if s == 200 and cnt_new != N_WRITE:
            DEFECTS.append(
                f"(count) race_new filtered count {cnt_new} != {N_WRITE} "
                f"(acked writes) - Type4_StateLogicViolation")

        # ---- env events: healthz-gated; >=2 events = Type3, 1 = transient ----
        if env_events:
            dead = [e for e in env_events if not e[3]]
            if dead:
                print(f"SCRIPT_ERROR note: healthz dead during env "
                      f"events: {dead[:3]}")
                return "SCRIPT_ERROR"
            if len(env_events) >= 2:
                DEFECTS.append(
                    f"(env) {len(env_events)} transport/5xx events while "
                    f"/healthz alive during index churn - "
                    f"Type3_RuntimeFailure - first={env_events[0]}")
            else:
                print(f"[env] single sporadic event logged as transient "
                      f"(reproduction rule, not a defect): {env_events[0]}")

        DEFECTS.extend(violations)

        # ---- summary ----
        print(f"[summary] total={total} race_new={cnt_new} "
              f"writer_acked={w_ok[0]}/{N_WRITE} env_events={len(env_events)} "
              f"violations={len(violations)} defects={len(DEFECTS)}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("concurrent index-deletion churn clean: all lifecycle deletes "
              "200, readers always saw exactly the expected filtered count, "
              "all writes landed, post-race totals and baseline payloads "
              f"exact ({N_BASE}+{N_WRITE}) - NO_DEFECT")
        return "NO_DEFECT"
    finally:
        # cleanup (own data only; failure must not flip the verdict)
        try:
            stop_evt.set()
        except Exception:
            pass
        try:
            rt.drop_collection(C)
            print(f"[cleanup] dropped {C}")
        except Exception as e:
            print(f"[cleanup] drop {C} failed (ignored): {e}")


if __name__ == "__main__":
    try:
        _v = main()
    except Exception:
        import traceback
        traceback.print_exc()
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
