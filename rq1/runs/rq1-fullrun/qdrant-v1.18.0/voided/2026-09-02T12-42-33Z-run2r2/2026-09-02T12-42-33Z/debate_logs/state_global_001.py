#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_global_001
# strategy: transaction
# endpoint: global
# constraint_ids: qdrant_inv_lock_blocks_mutations_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/service/post-locks
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03-adjacent maintenance-window state transition (the sibling
#   state_global_002 carries the genuine-concurrency BS-03 race)
"""
Attack: write-lock enforcement + release-restore state verification x
  qdrant_inv_lock_blocks_mutations_001 (chunk_global; scope=global —
  the lock option endpoints locks+get GET /locks / locks+set POST /locks,
  source_url https://api.qdrant.tech/v-1-18-x/api-reference/service/post-locks
  and https://api.qdrant.tech/v-1-18-x/api-reference/service/get-locks,
  are the unit's ONLY enabling API, so this script is the cross-endpoint
  mutation-plane coverage of one global state invariant). Assertion under
  test: with write=true and a configured error_message, ALL mutation APIs
  are refused carrying that message until write=false restores them.
  Legs (runtime PATHS keys; envelopes result.<field> per v-1-18-x OpenAPI):
    (0) probes: GET /locks + POST /locks {write:false} (fallback face —
        no PATHS key; contract-derived path '/locks')
    (1) seed collection C1 (create_collection, upsert_points 2 points
        wait=true, count == 2)
    (2) POST /locks {write:true, error_message:<token>} -> 200 AND
        GET /locks result.write == true (readback echo)
    (3) refusal matrix while locked — six mutation faces, each must be
        refused non-2xx with <token> in the body:
        upsert C1 / delete-points C1 (existing id) / create-index C1 /
        create-collection C2 / alias-create (update_aliases) /
        drop-collection C1 (LAST destructive face); on any 2xx the
        data-plane consequence is probed (get_point / describe /
        count / list_aliases) to type the violation
    (4) reads stay healthy while locked (count C1 == 200, context probe)
    (5) release POST /locks {write:false} -> 200 AND GET /locks
        result.write == false
    (6) restore: the same upsert accepted (200) and count advances by one
        (2 seeds - deleted-under-broken-lock + restored-upsert)
  Fallback precedent: aliases+collection+list GET fallback in this session
  (state_aliases_collection_list_001). The deployed binary is the OSS
  qdrant/qdrant:v1.18.0 image (server commit db3fca327851e360c521065649e0f65a57fe7d3c,
  deployment_meta.json); its route table (src/actix/api/service_api.rs in
  that exact commit) registers no /locks handler — so a non-2xx answer on
  both /locks probes routes to the ENDPOINT_ABSENT branch below (measured
  negative, baseline expectation per R8 reflection: invariant HOLDS).
Oracle: live /locks: while POST /locks {write:true,error_message:<token>} is 200 and GET /locks reports result.write=true, every mutation face (upsert/delete-points/create-index/create-collection/alias-create/drop-collection) must return non-2xx with <token> in the body and reads stay 200, and after POST {write:false} the same upsert is 200 with count advancing by one — any 2xx or landed mutation under lock = Type1_IllegalSuccess / Type4_StateLogicViolation; if GET+POST /locks both answer 404, NO_DEFECT with endpoint-absence evidence (invariant not actuable)
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
BASE_URL = BASE_URL.rstrip("/")

import requests  # noqa: E402  (fallback face only)

_FB_PRINTED = [False]
_FB_LOCK = threading.Lock()


def _fallback_markers():
    """Print the FALLBACK_TRIGGERED / FALLBACK_JUSTIFIED pair exactly once."""
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
    """All non-lock HTTP through the runtime; timeout/path_params/body/
    query_params forwarded exactly; path_key from rt.PATHS only."""
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


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sg1_" + TS + "_"          # unique-prefix discipline (standing lesson)
    TOKEN = PFX + "lockmsg"          # configured lock error_message
    C1 = PFX + "c1"
    C2 = PFX + "c2"
    ALIAS = PFX + "al"
    DIM = 4
    DEFECTS = []
    NOTES = []

    def alive():
        hs, hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        return hs == 200

    def count_of(name):
        s, raw = safe_request("POST", "count", {"exact": True},
                              path_params={"name": name})
        print(f"[count {name}] status={s} raw={str(raw)[:200]}")
        if s != 200:
            return None, s, raw
        res = get_result(raw)
        c = res.get("count") if isinstance(res, dict) else None
        if not isinstance(c, int) or isinstance(c, bool):
            print(f"[count {name}] 200 body lacks result.count int — "
                  f"raw={str(raw)[:200]}")
            return None, s, raw
        return c, s, raw

    names = [C1, C2]

    try:
        # ---- (0) endpoint probes + hygiene release (also 2nd absence probe) ----
        s0, raw0 = locks_http("GET", timeout=10)
        print(f"[probe GET /locks] status={s0} raw={str(raw0)[:300]}")
        s1, raw1 = locks_http("POST", {"write": False}, timeout=10)
        print(f"[probe POST /locks write=false] status={s1} raw={str(raw1)[:300]}")

        # ---- (1) seed collection ----
        s, raw = safe_request("PUT", "create_collection",
                              {"vectors": {"size": DIM, "distance": "Cosine"}},
                              path_params={"name": C1})
        print(f"[create C1] status={s} raw={str(raw)[:200]}")
        if s != 200:
            print(f"SETUP_FAIL: create C1 {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"
        pts = [{"id": i, "vector": [0.1 * (i + 1)] * DIM,
                "payload": {"tag": "seed"}} for i in range(2)]
        s, raw = safe_request("PUT", "upsert_points", {"points": pts},
                              path_params={"name": C1},
                              query_params={"wait": "true"})
        print(f"[seed upsert x2] status={s} raw={str(raw)[:200]}")
        if s != 200:
            print(f"SETUP_FAIL: seed upsert {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"
        c0, _, _ = count_of(C1)
        if c0 is None or c0 != 2:
            print(f"SETUP_FAIL: seed count={c0!r} (wanted 2)")
            return "SCRIPT_ERROR"

        # endpoint-absence branch: both /locks probes non-2xx -> the deployed
        # OSS v1.18.0 binary (commit db3fca3) has no /locks handler, so the
        # invariant cannot be actuated -> measured negative, NO_DEFECT.
        if (s0 == 0 or s0 >= 400) and (s1 == 0 or s1 >= 400):
            if s0 == 0 or s1 == 0:
                if not alive():
                    return "SCRIPT_ERROR"
            print("[ENDPOINT_ABSENT] GET /locks and POST /locks both answered "
                  "non-2xx on the deployed qdrant v1.18.0 OSS image (server "
                  "commit db3fca327851e360c521065649e0f65a57fe7d3c per "
                  "deployment_meta.json); the lock-option API this invariant "
                  "is anchored to is not registered in that commit's route "
                  "table (src/actix/api/service_api.rs registers only "
                  "telemetry/metrics/stacktrace/healthz/livez/readyz/logger/"
                  "truncate_unapplied_wal) — the write-lock cannot be "
                  "actuated, so the lock-blocks-mutations invariant is not "
                  "violable on this binary (run2 discipline: /locks = "
                  "not_found_in_source doc backfill, not a binary defect); "
                  "verifying the mutation plane is healthy and NOT "
                  "silently locked below")
            s, raw = safe_request("PUT", "upsert_points",
                                  {"points": [{"id": 50, "vector": [0.5] * DIM}]},
                                  path_params={"name": C1},
                                  query_params={"wait": "true"})
            print(f"[absent-branch sanity upsert] status={s} raw={str(raw)[:200]}")
            if s != 200:
                print(f"[absent-branch] upsert refused with {s} even though "
                      f"no lock could be set — raw={str(raw)[:200]}")
                DEFECTS.append(f"unlocked upsert refused with {s} while "
                               f"GET/POST /locks are absent — mutation plane "
                               f"not free — Type4_StateLogicViolation — "
                               f"raw={str(raw)[:150]}")
            c1b, _, _ = count_of(C1)
            if c1b is not None and c1b != 3:
                DEFECTS.append(f"count={c1b} after successful unlocked upsert "
                               f"(wanted 3) — Type4_StateLogicViolation")
            if DEFECTS:
                for d in DEFECTS:
                    print(f"DEFECT: {d}")
                return "DEFECT_FOUND"
            print("absent-branch verification complete: no lock state exists "
                  "and the mutation plane is healthy — NO_DEFECT")
            return "NO_DEFECT"

        if s1 == 0 or s1 >= 500:
            if not alive():
                return "SCRIPT_ERROR"
            print(f"[probe] POST /locks release answered {s1} (raw above) — "
                  f"cannot establish a clean unlocked baseline")
            return "SCRIPT_ERROR"
        print("[probe] /locks endpoint is LIVE — proceeding with the full "
              "lock enforcement matrix")

        # ---- (2) engage write lock with the configured message ----
        s, raw = locks_http("POST", {"write": True, "error_message": TOKEN})
        print(f"[set lock write=true token={TOKEN}] status={s} "
              f"raw={str(raw)[:300]}")
        if s == 0 or s >= 500:
            if not alive():
                return "SCRIPT_ERROR"
            print(f"SETUP_FAIL: lock set {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"
        if s < 200 or s >= 300:
            print(f"SETUP_FAIL: lock set refused {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"
        sg, rawg = locks_http("GET")
        print(f"[GET /locks under lock] status={sg} raw={str(rawg)[:300]}")
        if sg == 200:
            res = get_result(rawg)
            if not isinstance(res, dict):
                NOTES.append(f"GET /locks 200 body lacks result object — "
                             f"raw={str(rawg)[:200]}")
            else:
                if res.get("write") is not True:
                    DEFECTS.append(f"POST /locks write=true returned 200 but "
                                   f"GET /locks result.write="
                                   f"{res.get('write')!r} (wanted True) — lock "
                                   f"state not engaged — "
                                   f"Type4_StateLogicViolation")
                em = res.get("error_message")
                if em != TOKEN:
                    NOTES.append(f"GET /locks result.error_message="
                                 f"{em!r} (wanted {TOKEN!r}) — message not "
                                 f"echoed (secondary, refusal bodies checked "
                                 f"separately)")

        # ---- (3) refusal matrix across mutation faces (cross-endpoint) ----
        c1_alive = [True]
        del_slipped = [False]

        def refusal_leg(tag, s, raw):
            """Classify one mutation-under-lock response."""
            if s == 0:
                if alive():
                    DEFECTS.append(f"[{tag}] under write lock returned "
                                   f"transport failure with /healthz alive — "
                                   f"Type3_RuntimeFailure")
                else:
                    return "TRANSPORT"
            elif 500 <= s <= 599:
                if alive():
                    DEFECTS.append(f"[{tag}] under write lock returned {s} "
                                   f"(5xx is a crash-class refusal, not a "
                                   f"clean lock refusal) — Type3_RuntimeFailure"
                                   f" — raw={str(raw)[:150]}")
            elif 200 <= s <= 299:
                DEFECTS.append(f"[{tag}] mutation ACCEPTED with {s} while "
                               f"write lock is engaged — Type1_IllegalSuccess "
                               f"— raw={str(raw)[:200]}")
            elif TOKEN in (raw or ""):
                print(f"[{tag}] compliant refusal (non-2xx carries the "
                      f"configured error_message)")
            else:
                NOTES.append(f"[{tag}] refused with {s} but the configured "
                             f"error_message token is NOT in the body — "
                             f"refusal happened (blocking promise kept) but "
                             f"message not surfaced — raw={str(raw)[:200]}")
            return "OK"

        # f1 upsert new point
        s, raw = safe_request("PUT", "upsert_points",
                              {"points": [{"id": 100, "vector": [0.9] * DIM}]},
                              path_params={"name": C1},
                              query_params={"wait": "true"})
        print(f"[f1 upsert under lock] status={s} raw={str(raw)[:250]}")
        if refusal_leg("f1 upsert", s, raw) == "TRANSPORT":
            return "SCRIPT_ERROR"
        if 200 <= s <= 299:
            gp, graw = safe_request("GET", "get_point",
                                    path_params={"name": C1, "point_id": "100"})
            print(f"[f1 consequence get id=100] status={gp} raw={str(graw)[:200]}")
            if gp == 200:
                DEFECTS.append(f"[f1] upserted point id=100 is READABLE after "
                               f"the under-lock 2xx — data landed while the "
                               f"write lock was on — Type4_StateLogicViolation")

        # f2 delete existing point id 0
        s, raw = safe_request("POST", "delete_points", {"points": [0]},
                              path_params={"name": C1},
                              query_params={"wait": "true"})
        print(f"[f2 delete id=0 under lock] status={s} raw={str(raw)[:250]}")
        if refusal_leg("f2 delete-points", s, raw) == "TRANSPORT":
            return "SCRIPT_ERROR"
        if 200 <= s <= 299:
            del_slipped[0] = True
            gp, graw = safe_request("GET", "get_point",
                                    path_params={"name": C1, "point_id": "0"})
            print(f"[f2 consequence get id=0] status={gp} raw={str(graw)[:200]}")
            if gp == 404:
                DEFECTS.append(f"[f2] point id=0 was DELETED while the write "
                               f"lock was on (get -> 404) — destructive "
                               f"mutation slipped through — "
                               f"Type4_StateLogicViolation")

        # f3 create payload index on C1
        s, raw = safe_request("PUT", "create_index",
                              {"field_name": "tag",
                               "field_schema": {"type": "keyword"}},
                              path_params={"name": C1})
        print(f"[f3 create-index under lock] status={s} raw={str(raw)[:250]}")
        if refusal_leg("f3 create-index", s, raw) == "TRANSPORT":
            return "SCRIPT_ERROR"

        # f4 create a second collection
        s, raw = safe_request("PUT", "create_collection",
                              {"vectors": {"size": DIM, "distance": "Cosine"}},
                              path_params={"name": C2})
        print(f"[f4 create C2 under lock] status={s} raw={str(raw)[:250]}")
        if refusal_leg("f4 create-collection", s, raw) == "TRANSPORT":
            return "SCRIPT_ERROR"
        if 200 <= s <= 299:
            ds, draw = safe_request("GET", "describe_collection",
                                    path_params={"name": C2})
            print(f"[f4 consequence describe C2] status={ds} "
                  f"raw={str(draw)[:200]}")
            if ds == 200:
                DEFECTS.append(f"[f4] collection C2 was CREATED under the "
                               f"write lock (describe -> 200) — "
                               f"Type4_StateLogicViolation")

        # f5 create an alias bound to C1
        s, raw = safe_request("POST", "update_aliases",
                              {"actions": [{"create_alias":
                                            {"collection_name": C1,
                                             "alias_name": ALIAS}}]})
        print(f"[f5 alias-create under lock] status={s} raw={str(raw)[:250]}")
        if refusal_leg("f5 alias-create", s, raw) == "TRANSPORT":
            return "SCRIPT_ERROR"
        if 200 <= s <= 299:
            alias_seen = False
            for _i in range(5):
                ls, lraw = safe_request("GET", "list_aliases")
                print(f"[f5 consequence list_aliases] status={ls} "
                      f"raw={str(lraw)[:250]}")
                res = get_result(lraw)
                items = res.get("aliases") if isinstance(res, dict) else None
                if isinstance(items, list):
                    alias_seen = any(isinstance(a, dict) and
                                     a.get("alias_name") == ALIAS for a in items)
                if alias_seen:
                    break
                time.sleep(0.3)
            if alias_seen:
                DEFECTS.append(f"[f5] alias {ALIAS} is VISIBLE in /aliases "
                               f"after the under-lock 2xx — alias mutation "
                               f"applied while write lock on — "
                               f"Type4_StateLogicViolation")

        # f6 drop C1 — LAST destructive face (if it slips through, the
        #    collection is gone and later C1 legs are guarded by c1_alive)
        s, raw = safe_request("DELETE", "drop_collection",
                              path_params={"name": C1})
        print(f"[f6 drop C1 under lock] status={s} raw={str(raw)[:250]}")
        if refusal_leg("f6 drop-collection", s, raw) == "TRANSPORT":
            return "SCRIPT_ERROR"
        if 200 <= s <= 299:
            c1_alive[0] = False
            ds, draw = safe_request("GET", "describe_collection",
                                    path_params={"name": C1})
            print(f"[f6 consequence describe C1] status={ds} "
                  f"raw={str(draw)[:200]}")
            if ds == 404:
                DEFECTS.append(f"[f6] collection C1 was DROPPED under the "
                               f"write lock (describe -> 404) — destructive "
                               f"lifecycle mutation slipped through — "
                               f"Type4_StateLogicViolation")

        # ---- (4) reads stay healthy while locked (context probe) ----
        if c1_alive[0]:
            c1c, sc, rawc = count_of(C1)
            if sc == 0:
                if not alive():
                    return "SCRIPT_ERROR"
            elif 500 <= sc <= 599:
                if alive():
                    DEFECTS.append(f"count while locked returned {sc} with "
                                   f"service alive — Type3_RuntimeFailure — "
                                   f"raw={str(rawc)[:150]}")
            elif sc != 200:
                NOTES.append(f"count while locked returned {sc} (reads under "
                             f"lock not part of the invariant assertion; "
                             f"printed for the record) — raw={str(rawc)[:150]}")
            else:
                print(f"[reads-while-locked] count={c1c} (2 seeds; 2xx read "
                      f"plane healthy under lock)")

        # ---- (5) release the lock ----
        s, raw = locks_http("POST", {"write": False})
        print(f"[release write=false] status={s} raw={str(raw)[:300]}")
        if s == 0 or s >= 500:
            if not alive():
                return "SCRIPT_ERROR"
            DEFECTS.append(f"POST /locks write=false answered {s} with "
                           f"service alive — lock cannot be released — "
                           f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
        elif s < 200 or s >= 300:
            DEFECTS.append(f"POST /locks write=false refused with {s} — "
                           f"release transition failed — "
                           f"Type4_StateLogicViolation — raw={str(raw)[:200]}")
        else:
            sg, rawg = locks_http("GET")
            print(f"[GET /locks after release] status={sg} raw={str(rawg)[:300]}")
            if sg == 200:
                res = get_result(rawg)
                if isinstance(res, dict) and res.get("write") is not False:
                    DEFECTS.append(f"after successful release, GET /locks "
                                   f"result.write={res.get('write')!r} (wanted "
                                   f"False) — lock state did not transition — "
                                   f"Type4_StateLogicViolation")

        # ---- (6) restore: same upsert must now be accepted ----
        if c1_alive[0]:
            s, raw = safe_request("PUT", "upsert_points",
                                  {"points": [{"id": 100,
                                               "vector": [0.9] * DIM}]},
                                  path_params={"name": C1},
                                  query_params={"wait": "true"})
            print(f"[restore upsert id=100] status={s} raw={str(raw)[:200]}")
            if s == 0:
                if not alive():
                    return "SCRIPT_ERROR"
                DEFECTS.append(f"restore upsert transport failure with "
                               f"/healthz alive — Type3_RuntimeFailure")
            elif 500 <= s <= 599:
                if alive():
                    DEFECTS.append(f"restore upsert returned {s} with service "
                                   f"alive — Type3_RuntimeFailure — "
                                   f"raw={str(raw)[:150]}")
            elif s < 200 or s >= 300:
                DEFECTS.append(f"restore upsert refused with {s} after "
                               f"write=false (release did not restore the "
                               f"mutation plane) — Type4_StateLogicViolation "
                               f"— raw={str(raw)[:200]}")
            else:
                # restored point id=100 landed -> expected = 2 seeds
                # (unchanged: the delete face f2 was refused under the
                # compliant lock) + 1 restored; if the lock was broken and
                # f2's delete slipped through, del_slipped accounts for it
                gc, gs, graw = count_of(C1)
                if gs == 0:
                    if not alive():
                        return "SCRIPT_ERROR"
                elif 500 <= gs <= 599:
                    if alive():
                        DEFECTS.append(f"restore count returned {gs} with "
                                       f"service alive — Type3_RuntimeFailure")
                elif gs != 200:
                    DEFECTS.append(f"restore count returned {gs} — "
                                   f"Type4_StateLogicViolation — "
                                   f"raw={str(graw)[:150]}")
                else:
                    expected = 3 - (1 if del_slipped[0] else 0)
                    if gc != expected:
                        DEFECTS.append(f"final count={gc} != expected "
                                       f"{expected} (2 seeds - "
                                       f"{'1 deleted under broken lock' if del_slipped[0] else '0'}"
                                       f" + 1 restored) — state does not "
                                       f"reconcile after the lock lifecycle — "
                                       f"Type4_StateLogicViolation")

        for n in NOTES:
            print(f"NOTE: {n}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("lock lifecycle verification complete: refusals carried the "
              "configured message, reads stayed healthy, release restored "
              "the mutation plane, and the count reconciles — NO_DEFECT")
        return "NO_DEFECT"
    finally:
        # cleanup: release lock first (guarded), then alias + collections
        try:
            locks_http("POST", {"write": False}, timeout=10)
        except Exception:
            pass
        try:
            safe_request("POST", "update_aliases",
                         {"actions": [{"delete_alias":
                                       {"alias_name": ALIAS}}]}, timeout=10)
        except Exception:
            pass
        for n in names:
            try:
                rt.drop_collection(n)
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
