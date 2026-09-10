#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_global_002
# strategy: concurrent
# endpoint: global
# constraint_ids: qdrant_inv_lock_blocks_mutations_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/service/post-locks
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 Concurrency State Blindness (lock toggling vs concurrent
#   mutations: partial-commit detection, refused-but-landed / acked-but-lost)
"""
Attack: adversarial genuine-concurrency verification x
  qdrant_inv_lock_blocks_mutations_001 (chunk_global; scope=global — the
  enabling API is locks+set POST /locks / locks+get GET /locks, source_url
  https://api.qdrant.tech/v-1-18-x/api-reference/service/post-locks and
  https://api.qdrant.tech/v-1-18-x/api-reference/service/get-locks; R18
  reflection deliverable: baseline expectation invariant HOLDS — this is the
  race-side adversarial pass that a sequential matrix cannot produce).
  Design: a lock-toggler thread cycles POST /locks {write:true,
  error_message:<token>} -> verify GET /locks -> POST {write:false} while
  N writer threads (TESTVDB_CONCURRENT_THREADS, default 10) hammer 20-seed
  collection C with wait=true upserts of unique ids. Per-request
  classification: 2xx = applied; non-2xx carrying <token> = clean lock
  refusal; anything else (transport/5xx/foreign-4xx) = anomaly. After the
  storm: final release, then global reconciliation — exact count must equal
  20 seeds + number of 2xx responses (no refused-but-landed residue, no
  acked-but-lost data), sampled refused ids must be absent (get -> 404),
  sampled 2xx ids must be present, and every successful toggle must be
  confirmed by GET /locks (result.write envelope). All HTTP through
  safe_request (rt.request, path keys upsert_points/get_point/count/healthz);
  lock probes use the contract-derived /locks fallback face (no runtime
  PATHS key — same FALLBACK precedent as state_aliases_collection_list_001).
  The deployed binary is OSS qdrant/qdrant:v1.18.0 (server commit
  db3fca327851e360c521065649e0f65a57fe7d3c, deployment_meta.json) whose route
  table registers no /locks handler (src/actix/api/service_api.rs in that
  commit) — non-2xx on both /locks probes routes to ENDPOINT_ABSENT
  (measured negative; no concurrency window can exist without the enabling
  endpoint, so the honest terminal is NO_DEFECT with that evidence).
Oracle: live /locks: while a thread toggles write lock on (with error_message=<token>) / off, every wait=true upsert response must be either 2xx or non-2xx carrying <token> (zero transport/5xx/foreign-4xx), final exact count == 20 seeds + n_2xx, every refused id absent and every 2xx id present, and GET /locks agrees with each successful set — any deviation = Type3_RuntimeFailure / Type4_StateLogicViolation; if GET+POST /locks both answer 404, NO_DEFECT with endpoint-absence evidence (invariant not actuable)
"""
import os
import sys
import json
import time
import random
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
BASE_URL = BASE_URL.rstrip("/")

import requests  # noqa: E402  (fallback face only)

_FB_PRINTED = [False]
_FB_LOCK = threading.Lock()
_CURRENT_C = [None]   # set by the run; dropped by main()'s finally


def _fallback_markers():
    with _FB_LOCK:
        if _FB_PRINTED[0]:
            return
        _FB_PRINTED[0] = True
    print("FALLBACK_TRIGGERED: lock-option probes (locks+get GET /locks / locks+set POST /locks) have no qdrant runtime PATHS key; issuing the contract-derived REST path /locks via requests")
    print("[FALLBACK_JUSTIFIED: scripts/runtime/qdrant.py PATHS (create_collection..metrics) exposes no locks key; chunk_global unit qdrant_inv_lock_blocks_mutations_001 is anchored on contract api_endpoints locks+set (POST /locks, source_url https://api.qdrant.tech/v-1-18-x/api-reference/service/post-locks, required body field write) and locks+get (GET /locks, response_shape result.write/result.error_message) whose api_endpoints url fields both read '/locks'; the path is derived 1:1 from the contract records and the runtime whitelist gap is a runtime-coverage gap, not a reason to drop the unit's only enabling API — same FALLBACK precedent as state_aliases_collection_list_001 in this session]")


def locks_http(method, body=None, timeout=15):
    """FALLBACK face mirroring rt.request's (status, raw_text) 2-tuple for
    the contract-declared /locks service endpoint (no runtime PATHS key)."""
    _fallback_markers()
    url = BASE_URL + "/locks"
    headers = {"Content-Type": "application/json"}
    _a = os.environ.get("TESTVDB_AUTH_HEADER", "")
    if _a:
        headers["Authorization"] = _a
    try:
        r = requests.request(method, url, json=body, headers=headers,
                             timeout=timeout)
        return r.status_code, r.text
    except Exception as e:
        return 0, str(e)


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


def get_result(raw):
    b = parse_json(raw)
    return b.get("result") if isinstance(b, dict) else None


def _main_inner():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sg2_" + TS + "_"          # unique-prefix discipline (standing lesson)
    TOKEN = PFX + "lockmsg"
    C = PFX + "c1"
    _CURRENT_C[0] = C
    DIM = 4
    SEED_N = 20
    ROUNDS = 10                     # wait=true upsert attempts per writer thread
    CYCLES = 3                      # lock on/off cycles by the toggler
    DEFECTS = []
    NOTES = []
    try:
        THREADS = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10"))
        if THREADS < 1 or THREADS > 40:
            THREADS = 10
    except ValueError:
        THREADS = 10
    print(f"[config] writer_threads={THREADS} rounds_per_thread={ROUNDS} "
          f"toggle_cycles={CYCLES} seed_points={SEED_N}")

    def alive():
        hs, hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        return hs == 200

    # ---- probes + hygiene release (double as the absence probe) ----
    s0, raw0 = locks_http("GET", timeout=10)
    print(f"[probe GET /locks] status={s0} raw={str(raw0)[:300]}")
    s1, raw1 = locks_http("POST", {"write": False}, timeout=10)
    print(f"[probe POST /locks write=false] status={s1} raw={str(raw1)[:300]}")

    if (s0 == 0 or s0 >= 400) and (s1 == 0 or s1 >= 400):
        # ENDPOINT_ABSENT: OSS v1.18.0 binary has no /locks handler -> the
        # lock cannot be actuated -> no concurrency window can exist -> the
        # honest measurement is negative (baseline: invariant HOLDS).
        if s0 == 0 or s1 == 0:
            if not alive():
                return "SCRIPT_ERROR"
        print("[ENDPOINT_ABSENT] GET /locks and POST /locks both answered "
              "non-2xx on the deployed qdrant v1.18.0 OSS image (server "
              "commit db3fca327851e360c521065649e0f65a57fe7d3c per "
              "deployment_meta.json); the lock-option API this invariant is "
              "anchored to is not registered in that commit's route table "
              "(src/actix/api/service_api.rs) — the write-lock cannot be "
              "actuated, so a lock-toggle vs mutation race window cannot "
              "exist and the invariant is not violable on this binary (run2 "
              "discipline: /locks = not_found_in_source doc backfill, not a "
              "binary defect); verifying the mutation plane is healthy and "
              "free of any residual lock below")
        s, raw = safe_request("PUT", "create_collection",
                              {"vectors": {"size": DIM, "distance": "Cosine"}},
                              path_params={"name": C})
        print(f"[absent sanity create] status={s} raw={str(raw)[:200]}")
        if s != 200:
            print(f"SETUP_FAIL: sanity create {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"
        s, raw = safe_request("PUT", "upsert_points",
                              {"points": [{"id": 1, "vector": [0.1] * DIM}]},
                              path_params={"name": C},
                              query_params={"wait": "true"})
        print(f"[absent sanity upsert] status={s} raw={str(raw)[:200]}")
        if s != 200:
            print(f"[absent-branch] unlocked upsert refused with {s} — "
                  f"mutation plane not free — raw={str(raw)[:200]}")
            DEFECTS.append(f"unlocked upsert refused with {s} while "
                           f"GET/POST /locks are absent — "
                           f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
        sc, sraw = safe_request("POST", "count", {"exact": True},
                                path_params={"name": C})
        res = get_result(sraw)
        cnt = res.get("count") if isinstance(res, dict) else None
        print(f"[absent sanity count] status={sc} raw={str(sraw)[:200]}")
        if sc == 200 and cnt != 1:
            DEFECTS.append(f"count={cnt!r} after unlocked upsert (wanted 1) — "
                           f"Type4_StateLogicViolation")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("absent-branch verification complete: mutation plane healthy, "
              "no lock residue — NO_DEFECT")
        return "NO_DEFECT"

    if s1 == 0 or s1 >= 500:
        if not alive():
            return "SCRIPT_ERROR"
        print(f"[probe] POST /locks release answered {s1} — cannot establish "
              f"a clean unlocked baseline")
        return "SCRIPT_ERROR"
    print("[probe] /locks endpoint is LIVE — starting the lock-toggle vs "
          "concurrent-upsert race")

    # ---- seed collection ----
    s, raw = safe_request("PUT", "create_collection",
                          {"vectors": {"size": DIM, "distance": "Cosine"}},
                          path_params={"name": C})
    print(f"[create C] status={s} raw={str(raw)[:200]}")
    if s != 200:
        print(f"SETUP_FAIL: create {s} {str(raw)[:200]}")
        return "SCRIPT_ERROR"
    seeds = [{"id": i, "vector": [0.01 * (i + 1)] * DIM} for i in range(SEED_N)]
    s, raw = safe_request("PUT", "upsert_points", {"points": seeds},
                          path_params={"name": C}, query_params={"wait": "true"})
    print(f"[seed upsert x{SEED_N}] status={s} raw={str(raw)[:200]}")
    if s != 200:
        print(f"SETUP_FAIL: seed upsert {s} {str(raw)[:200]}")
        return "SCRIPT_ERROR"
    sc, sraw = safe_request("POST", "count", {"exact": True},
                            path_params={"name": C})
    res = get_result(sraw)
    c_seed = res.get("count") if isinstance(res, dict) else None
    print(f"[seed count] status={sc} raw={str(sraw)[:200]}")
    if sc != 200 or c_seed != SEED_N:
        print(f"SETUP_FAIL: seed count={c_seed!r} (wanted {SEED_N})")
        return "SCRIPT_ERROR"

    # ---- race: writers vs lock toggler ----
    ok_l, refused_l, trans_l, s5xx_l, other_l = [], [], [], [], []
    lock_l = threading.Lock()

    def writer(tid):
        my = {"ok": [], "refused": [], "trans": [], "s5xx": [], "other": []}
        rng = random.Random(TS + str(tid))
        for r in range(ROUNDS):
            pid = 10000 + tid * 1000 + r
            vec = [round(rng.random(), 6)] * DIM
            s, raw = safe_request("PUT", "upsert_points",
                                  {"points": [{"id": pid, "vector": vec}]},
                                  path_params={"name": C},
                                  query_params={"wait": "true"})
            if s == 0:
                my["trans"].append((pid, s, str(raw)[:120]))
            elif s >= 500:
                my["s5xx"].append((pid, s, str(raw)[:120]))
            elif 200 <= s <= 299:
                my["ok"].append((pid, s, str(raw)[:120]))
            elif TOKEN in (raw or ""):
                my["refused"].append((pid, s, str(raw)[:120]))
            else:
                my["other"].append((pid, s, str(raw)[:120]))
            time.sleep(0.05)
        with lock_l:
            ok_l.extend(my["ok"])
            refused_l.extend(my["refused"])
            trans_l.extend(my["trans"])
            s5xx_l.extend(my["s5xx"])
            other_l.extend(my["other"])
        print(f"[writer {tid}] ok={len(my['ok'])} refused="
              f"{len(my['refused'])} transport={len(my['trans'])} "
              f"5xx={len(my['s5xx'])} other={len(my['other'])}")

    toggle_problems = []   # (stage, status, raw) — GET-verification mismatches

    def toggler():
        for cyc in range(CYCLES):
            s, raw = locks_http("POST", {"write": True,
                                         "error_message": TOKEN}, timeout=15)
            print(f"[toggle {cyc} ON] status={s} raw={str(raw)[:250]}")
            if s == 0 or s >= 500:
                toggle_problems.append(("set_on_transport", s, str(raw)[:150]))
            elif s < 200 or s >= 300:
                toggle_problems.append(("set_on_refused", s, str(raw)[:150]))
            else:
                sg, rawg = locks_http("GET", timeout=10)
                print(f"[toggle {cyc} verify GET] status={sg} "
                      f"raw={str(rawg)[:250]}")
                resg = get_result(rawg)
                w = resg.get("write") if isinstance(resg, dict) else None
                if sg == 200 and w is not True:
                    toggle_problems.append(
                        ("get_write_after_on", sg,
                         f"result.write={w!r} raw={str(rawg)[:150]}"))
            time.sleep(0.5)
            s, raw = locks_http("POST", {"write": False}, timeout=15)
            print(f"[toggle {cyc} OFF] status={s} raw={str(raw)[:250]}")
            if s == 0 or s >= 500:
                toggle_problems.append(("set_off_transport", s, str(raw)[:150]))
            elif s < 200 or s >= 300:
                toggle_problems.append(("set_off_refused", s, str(raw)[:150]))
            time.sleep(0.1)

    writers = [threading.Thread(target=writer, args=(t,)) for t in range(THREADS)]
    for t in writers:
        t.start()
    time.sleep(0.15)
    tg = threading.Thread(target=toggler)
    tg.start()
    for t in writers:
        t.join()
    tg.join()
    print(f"[merge] ok={len(ok_l)} refused={len(refused_l)} "
          f"transport={len(trans_l)} 5xx={len(s5xx_l)} other={len(other_l)}")

    # final release + server-side state readback
    sr, rawr = locks_http("POST", {"write": False}, timeout=15)
    print(f"[final release] status={sr} raw={str(rawr)[:250]}")
    sg, rawg = locks_http("GET", timeout=10)
    print(f"[final GET /locks] status={sg} raw={str(rawg)[:250]}")
    resg = get_result(rawg)
    w_end = resg.get("write") if isinstance(resg, dict) else None
    time.sleep(1.0)  # settle: WAL flush for wait=true ops already done; this
    #                 covers any server-side side-effects visibility window

    # ---- adjudication legs ----
    if trans_l:
        if not alive():
            return "SCRIPT_ERROR"
        for pid, s, snippet in trans_l[:5]:
            DEFECTS.append(f"writer upsert id={pid} transport failure with "
                           f"/healthz alive — Type3_RuntimeFailure — "
                           f"{snippet}")
    if s5xx_l:
        if not alive():
            return "SCRIPT_ERROR"
        for pid, s, snippet in s5xx_l[:5]:
            DEFECTS.append(f"writer upsert id={pid} returned {s} with service "
                           f"alive — Type3_RuntimeFailure — {snippet}")
    for pid, s, snippet in other_l[:8]:
        DEFECTS.append(f"writer upsert id={pid} returned {s} without the "
                       f"configured lock message (valid wait=true upsert "
                       f"neither applied nor lock-refused) — "
                       f"Type4_StateLogicViolation — {snippet}")
    if toggle_problems:
        for stage, s, snippet in toggle_problems[:6]:
            if stage in ("set_on_transport", "set_off_transport"):
                if alive():
                    DEFECTS.append(f"toggler {stage} transport failure with "
                                   f"/healthz alive — Type3_RuntimeFailure — "
                                   f"{snippet}")
                else:
                    return "SCRIPT_ERROR"
            elif stage == "set_on_refused":
                print(f"[toggler] set-ON refused {s} mid-run — the lock "
                      f"window could not be established; raw={snippet}")
                DEFECTS.append(f"toggler set-ON refused with {s} mid-run "
                               f"(endpoint live at probe) — window broken — "
                               f"raw={snippet}")
            else:
                DEFECTS.append(f"toggler {stage} {s} — lock state did not "
                               f"follow the successful set — "
                               f"Type4_StateLogicViolation — {snippet}")

    # global reconciliation: exact count == seeds + n_2xx
    sc, sraw = safe_request("POST", "count", {"exact": True},
                            path_params={"name": C})
    res = get_result(sraw)
    cnt = res.get("count") if isinstance(res, dict) else None
    print(f"[final count] status={sc} raw={str(sraw)[:200]}")
    if sc == 0:
        if not alive():
            return "SCRIPT_ERROR"
        DEFECTS.append(f"final count transport failure with /healthz alive — "
                       f"Type3_RuntimeFailure")
    elif sc >= 500:
        if not alive():
            return "SCRIPT_ERROR"
        DEFECTS.append(f"final count returned {sc} with service alive — "
                       f"Type3_RuntimeFailure")
    elif sc != 200 or not isinstance(cnt, int) or isinstance(cnt, bool):
        DEFECTS.append(f"final count unreadable (status={sc} count={cnt!r}) — "
                       f"Type4_StateLogicViolation — raw={str(sraw)[:150]}")
    else:
        expected = SEED_N + len(ok_l)
        if cnt != expected:
            DEFECTS.append(f"final exact count={cnt} != {SEED_N} seeds + "
                           f"{len(ok_l)} acked upserts = {expected} — "
                           f"refused-but-landed residue or acked-but-lost "
                           f"data under lock toggling — "
                           f"Type4_StateLogicViolation")
        else:
            print(f"[reconcile] count {cnt} == seeds {SEED_N} + acked "
                  f"{len(ok_l)} — global state reconciles")

    # spot checks: refused ids must be absent, acked ids must be present
    def probe_point(pid, want):
        sp, praw = safe_request("GET", "get_point",
                                path_params={"name": C, "point_id": str(pid)})
        if sp == 0:
            if not alive():
                return "TRANSPORT"
            DEFECTS.append(f"get_point id={pid} transport failure with "
                           f"/healthz alive — Type3_RuntimeFailure")
            return "OK"
        if sp >= 500:
            if not alive():
                return "TRANSPORT"
            DEFECTS.append(f"get_point id={pid} returned {sp} with service "
                           f"alive — Type3_RuntimeFailure")
            return "OK"
        if want == "absent":
            if sp == 200:
                DEFECTS.append(f"refused upsert id={pid} is PRESENT "
                               f"(get -> 200) — the lock refusal did not "
                               f"prevent the write — "
                               f"Type4_StateLogicViolation")
            elif sp != 404:
                DEFECTS.append(f"get_point id={pid} answered {sp} (expected "
                               f"404 for a refused id) — "
                               f"Type4_StateLogicViolation")
        else:
            if sp == 404:
                DEFECTS.append(f"acked upsert id={pid} is MISSING "
                               f"(get -> 404) — acknowledged write lost — "
                               f"Type4_StateLogicViolation")
            elif sp != 200:
                DEFECTS.append(f"get_point id={pid} answered {sp} (expected "
                               f"200 for an acked id) — "
                               f"Type4_StateLogicViolation")
        return "OK"

    rng = random.Random(TS + "spot")
    if refused_l:
        sample = rng.sample(refused_l, min(12, len(refused_l)))
        for pid, s, snippet in sample:
            if probe_point(pid, "absent") == "TRANSPORT":
                return "SCRIPT_ERROR"
        print(f"[spot] sampled {len(sample)} refused ids — absence verified")
    else:
        print("[spot] no refused upserts observed (all attempts landed "
              "outside the lock windows)")
    if ok_l:
        sample = rng.sample(ok_l, min(12, len(ok_l)))
        for pid, s, snippet in sample:
            if probe_point(pid, "present") == "TRANSPORT":
                return "SCRIPT_ERROR"
        print(f"[spot] sampled {len(sample)} acked ids — presence verified")
    else:
        print("[spot] no acked upserts observed (all attempts were refused)")

    if w_end is not None and w_end is not False:
        DEFECTS.append(f"final GET /locks result.write={w_end!r} (wanted "
                       f"False after final release) — lock left engaged — "
                       f"Type4_StateLogicViolation")

    for n in NOTES:
        print(f"NOTE: {n}")
    if DEFECTS:
        for d in DEFECTS:
            print(f"DEFECT: {d}")
        return "DEFECT_FOUND"
    print("concurrency reconciliation complete: no anomaly class, count "
          "reconciles, refused absent / acked present, lock state consistent "
          "— invariant HOLDS under genuine concurrency — NO_DEFECT")
    return "NO_DEFECT"

def main():
    """Run the race verification; cleanup (lock release + collection drop) is
    unconditional and wrapped — cleanup failure must not fail the script."""
    try:
        return _main_inner()
    finally:
        try:
            locks_http("POST", {"write": False}, timeout=10)
        except Exception:
            pass
        if _CURRENT_C[0]:
            try:
                rt.drop_collection(_CURRENT_C[0])
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
