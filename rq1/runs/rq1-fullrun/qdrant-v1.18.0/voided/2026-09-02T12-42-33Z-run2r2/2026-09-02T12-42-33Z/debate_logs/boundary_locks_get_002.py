#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_locks_get_002
# strategy: behavioral
# endpoint: locks+get
# constraint_ids: qdrant_behavioral_locks_get_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/service/get-locks
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04-adjacent — read-face default optimism: assuming the GET
#   face answers 200 and reflects the CURRENT lock state without checking
#   currency across transitions (engage / re-engage with a new message /
#   release) and stability across repeated reads.
"""
TestVDB Boundary Attack Script — Target: qdrant v1.18.0
Attack: behavioral read-face promise attack (strategy=behavioral x
  qdrant_behavioral_locks_get_001; chunk_locks+get scope=locks+get GET
  /locks). Assertion under test (contract assertions[].expected_behavior):
  "HTTP 200 with {write: bool, error_message: string|null}" — the read
  face must answer 200 and report the CURRENT write-protection state.
  Positive: exercise the promise (200 + state reflection) in every
  actuated state. Negative constructions (G4): stale/wrong reflection
  after a transition, flapping across repeated reads, non-200 while the
  locks family is live, 5xx crash on the read face.
  State driver: POST /locks (locks+set) actuator only — its own faces
  belong to chunk_locks+set, not adjudicated here.
  Legs: (0) GET+POST /locks probes; (A) baseline GET must be 200;
  (B) engage write=true + error_message TOKEN_A -> GET (<=3 tries x
  0.3s settle allowance) must report result.write===True AND
  result.error_message===TOKEN_A (currency of the configured message);
  (C) re-engage still-locked with TOKEN_B -> GET must track TOKEN_B
  (message currency under re-set); (D) 5 immediate repeated GETs all
  200 with write===True and TOKEN_B (no flapping/stale cache);
  (E) release write=false -> GET (<=3 tries) must report
  result.write===False (timely release reflection; post-release
  error_message value is NOT asserted — the doc does not specify it).
  Dual-path per R19 (chunk_global) reflection: both probes concrete
  non-2xx (404 expected on this OSS v1.18.0 image — locks family absent
  from service_api.rs route table, cloud doc backfill) -> ENDPOINT_ABSENT
  -> NO_DEFECT with probe evidence (R19/R8 baseline); GET non-2xx while
  POST 2xx = interface-parity defect (G9); transport-0 probes with
  /healthz alive are NOT adjudicated as absence (honest SCRIPT_ERROR).
Oracle: live /locks: baseline GET 200; after POST {write:true,error_message:TOKEN_A} the GET (within 3 tries) reports result.write===True and result.error_message===TOKEN_A; after re-engage with TOKEN_B it tracks TOKEN_B; 5 repeated GETs stay 200/write===True/TOKEN_B; after POST {write:false} the GET (within 3 tries) reports result.write===False — wrong/stale state = Type4_StateLogicViolation, non-200 while live = Type4 (broken 200 promise), 5xx with /healthz alive = Type3_RuntimeFailure; if GET+POST /locks both answer concrete non-2xx (404 expected), NO_DEFECT with endpoint-absence evidence (assertion not actuable)
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
BASE_URL = BASE_URL.rstrip("/")

import requests  # noqa: E402  (fallback face only)

_FB_PRINTED = [False]


def _fallback_markers():
    """Print the FALLBACK_TRIGGERED / FALLBACK_JUSTIFIED pair exactly once."""
    if _FB_PRINTED[0]:
        return
    _FB_PRINTED[0] = True
    print("FALLBACK_TRIGGERED: locks read-face probe (locks+get GET /locks) and its locks+set POST /locks actuator have no qdrant runtime PATHS key; issuing the contract-derived REST path /locks via requests")
    print("[FALLBACK_JUSTIFIED: scripts/runtime/qdrant.py PATHS (create_collection..metrics) exposes no locks key; chunk_locks+get unit qdrant_behavioral_locks_get_001 is anchored on contract api_endpoints locks+get (GET, expected_responses 200=LocksOption{write,error_message}) whose raw_knowledge api_endpoints url field reads '/locks', with locks+set (POST /locks, required body field write) as the only state actuator; both paths are derived 1:1 from the contract records and the runtime whitelist gap is a runtime-coverage gap, not a reason to drop the unit — same FALLBACK precedent as state_global_001 in this session]")


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


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "lgb1_" + TS + "_"          # unique-prefix discipline (standing lesson)
    TOKEN_A = PFX + "currmsgA"
    TOKEN_B = PFX + "currmsgB"
    DEFECTS = []
    NOTES = []

    def alive():
        hs, hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        return hs == 200

    def read_state(tag):
        """One GET /locks read. Returns (state_tuple, status) where
        state_tuple=(write, error_message) when parseable, else None.
        Classifies non-200/5xx/transport directly (G8 three-outcome)."""
        s, raw = locks_http("GET", timeout=15)
        print(f"[{tag}] status={s} raw={str(raw)[:300]}")
        if s == 0:
            if not alive():
                return None, "TRANSPORT"
            DEFECTS.append(f"[{tag}] GET /locks transport failure with "
                           f"/healthz alive — Type3_RuntimeFailure")
            return None, "OK"
        if 500 <= s <= 599:
            if alive():
                DEFECTS.append(f"[{tag}] GET /locks returned {s} with "
                               f"/healthz alive — Type3_RuntimeFailure — "
                               f"raw={str(raw)[:150]}")
            else:
                return None, "TRANSPORT"
            return None, "OK"
        if not (200 <= s <= 299):
            DEFECTS.append(f"[{tag}] GET /locks answered {s} while the locks "
                           f"family is live — the documented read-face "
                           f"promise (HTTP 200 with current state) is broken "
                           f"— Type4_StateLogicViolation — "
                           f"raw={str(raw)[:150]}")
            return None, "OK"
        res = parse_json(raw).get("result") if parse_json(raw) else None
        if not isinstance(res, dict):
            DEFECTS.append(f"[{tag}] GET /locks 200 body lacks a result "
                           f"object (promise: 200 with LocksOption state) — "
                           f"Type1_IllegalSuccess — raw={str(raw)[:200]}")
            return None, "OK"
        w = res.get("write")
        if not isinstance(w, bool):
            DEFECTS.append(f"[{tag}] result.write={w!r} "
                           f"({type(w).__name__}) is not a boolean — the "
                           f"promise states write: bool — "
                           f"Type1_IllegalSuccess — raw={str(raw)[:200]}")
        return (w, res.get("error_message")), "OK"

    def read_state_settled(tag, tries=3):
        """Read with a small settle allowance after a transition (the POST
        actuator is expected synchronous; retries only guard fair reading,
        the FINAL read is the asserted one)."""
        st = None
        for i in range(tries):
            st, outcome = read_state(f"{tag} try#{i + 1}")
            if outcome == "TRANSPORT" or st is not None:
                return st, outcome
            time.sleep(0.3)
        return st, outcome

    try:
        # ---- (0) endpoint probes (GET read face + POST hygiene release) ----
        s0, raw0 = locks_http("GET", timeout=10)
        print(f"[probe GET /locks] status={s0} raw={str(raw0)[:300]}")
        s1, raw1 = locks_http("POST", {"write": False}, timeout=10)
        print(f"[probe POST /locks write=false] status={s1} raw={str(raw1)[:300]}")

        if s0 == 0 or s1 == 0:
            if not alive():
                return "SCRIPT_ERROR"
            print("[probe-anomaly] transport failure (status=0) on a /locks "
                  "probe while /healthz is alive — cannot honestly adjudicate "
                  "endpoint absence vs read-face defect -> SCRIPT_ERROR "
                  "(stricter than R19: absence requires a concrete HTTP "
                  "non-2xx status on BOTH probes)")
            return "SCRIPT_ERROR"

        get_live = 200 <= s0 <= 299
        post_live = 200 <= s1 <= 299

        if not get_live and not post_live:
            print("[ENDPOINT_ABSENT] GET /locks and POST /locks both answered "
                  f"concrete non-2xx statuses ({s0} / {s1}) on the deployed "
                  "qdrant v1.18.0 OSS image (server commit "
                  "db3fca327851e360c521065649e0f65a57fe7d3c per "
                  "deployment_meta.json); the locks read face this behavioral "
                  "assertion is anchored to is not registered in that "
                  "commit's route table (src/actix/api/service_api.rs "
                  "registers only telemetry/metrics/stacktrace/healthz/"
                  "livez/readyz/logger/truncate_unapplied_wal) — R19 "
                  "(chunk_global) measured the same 404 pair, R8 baseline: "
                  "/locks = not_found_in_source cloud doc backfill, so the "
                  "'200 with current lock state' promise is not actuable on "
                  "this binary and cannot be violated — NO_DEFECT (measured "
                  "negative with probe evidence above)")
            return "NO_DEFECT"

        if not get_live and post_live:
            DEFECTS.append(f"interface parity: GET /locks answered {s0} "
                           f"(non-2xx) while POST /locks answered {s1} — the "
                           f"locks family IS live (route registered) but the "
                           f"documented read face (200 + current lock state, "
                           f"source_url https://api.qdrant.tech/v-1-18-x/"
                           f"api-reference/service/get-locks) is missing — "
                           f"Type4_StateLogicViolation (G9 same-family face "
                           f"asymmetry) — GET raw={str(raw0)[:150]}")
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"

        # ---- (A) baseline: the 200 promise itself ----
        st, outcome = read_state("A baseline")
        if outcome == "TRANSPORT":
            return "SCRIPT_ERROR"
        baseline_write = st[0] if st else None
        print(f"[A baseline] observed write={baseline_write!r}")

        if not post_live:
            NOTES.append(f"POST /locks actuator probe answered {s1} while GET "
                         f"is live — engage/re-engage/release currency legs "
                         f"(B/C/D/E) need the actuator; only the baseline "
                         f"promise was actuable this run (locks+set faces "
                         f"belong to chunk_locks+set)")
            for n in NOTES:
                print(f"NOTE: {n}")
            if DEFECTS:
                for d in DEFECTS:
                    print(f"DEFECT: {d}")
                return "DEFECT_FOUND"
            return "NO_DEFECT"

        # ---- (B) engage TOKEN_A -> read-face currency ----
        se, rawe = locks_http("POST", {"write": True,
                                       "error_message": TOKEN_A}, timeout=15)
        print(f"[engage write=true token={TOKEN_A}] status={se} "
              f"raw={str(rawe)[:300]}")
        if not (200 <= se <= 299):
            NOTES.append(f"engage POST answered {se} — currency legs skipped "
                         f"(actuator face out of this chunk's scope) — "
                         f"raw={str(rawe)[:150]}")
        else:
            st, outcome = read_state_settled("B after engage TOKEN_A")
            if outcome == "TRANSPORT":
                return "SCRIPT_ERROR"
            if st is not None:
                w, em = st
                if w is not True:
                    DEFECTS.append(f"after POST write=true (answered {se}), "
                                   f"GET reports result.write={w!r} (wanted "
                                   f"True) — read face does not reflect the "
                                   f"current lock state — "
                                   f"Type4_StateLogicViolation")
                if em != TOKEN_A:
                    DEFECTS.append(f"after POST write=true with "
                                   f"error_message={TOKEN_A!r}, GET reports "
                                   f"result.error_message={em!r} — configured "
                                   f"message not reflected on the read face "
                                   f"(doc: GET returns the current lock state "
                                   f"LocksOption incl. error_message) — "
                                   f"Type4_StateLogicViolation (judge: "
                                   f"state-currency incompleteness)")

            # ---- (C) re-engage with TOKEN_B (still locked) -> message tracks ----
            se2, rawe2 = locks_http("POST", {"write": True,
                                             "error_message": TOKEN_B},
                                    timeout=15)
            print(f"[re-engage write=true token={TOKEN_B}] status={se2} "
                  f"raw={str(rawe2)[:300]}")
            if not (200 <= se2 <= 299):
                NOTES.append(f"re-engage POST answered {se2} — message-"
                             f"currency leg C and stability leg D run against "
                             f"TOKEN_A state instead — raw={str(rawe2)[:150]}")
                want_msg = TOKEN_A
            else:
                want_msg = TOKEN_B
            st, outcome = read_state_settled("C after re-engage")
            if outcome == "TRANSPORT":
                return "SCRIPT_ERROR"
            if st is not None:
                w, em = st
                if w is not True:
                    DEFECTS.append(f"after re-engage (write=true), GET "
                                   f"reports result.write={w!r} (wanted "
                                   f"True) — Type4_StateLogicViolation")
                if em != want_msg:
                    DEFECTS.append(f"after re-engage with "
                                   f"error_message={want_msg!r}, GET reports "
                                   f"result.error_message={em!r} — the read "
                                   f"face does not track message re-set "
                                   f"(stale state) — "
                                   f"Type4_StateLogicViolation")

            # ---- (D) stability: 5 immediate repeated reads ----
            for i in range(5):
                st, outcome = read_state(f"D stability #{i + 1}")
                if outcome == "TRANSPORT":
                    return "SCRIPT_ERROR"
                if st is not None:
                    w, em = st
                    if w is not True:
                        DEFECTS.append(f"repeated read #{i + 1} flapped: "
                                       f"result.write={w!r} while the lock "
                                       f"is engaged — "
                                       f"Type4_StateLogicViolation")
                    elif em != want_msg:
                        DEFECTS.append(f"repeated read #{i + 1} reports "
                                       f"result.error_message={em!r} != "
                                       f"{want_msg!r} — read face flapping/"
                                       f"stale — Type4_StateLogicViolation")

        # ---- (E) release -> timely reflection ----
        sr, rawr = locks_http("POST", {"write": False}, timeout=15)
        print(f"[release write=false] status={sr} raw={str(rawr)[:300]}")
        if 200 <= sr <= 299:
            st, outcome = read_state_settled("E after release")
            if outcome == "TRANSPORT":
                return "SCRIPT_ERROR"
            if st is not None and st[0] is not False:
                DEFECTS.append(f"after POST write=false (answered {sr}), GET "
                               f"reports result.write={st[0]!r} (wanted "
                               f"False) — release not reflected on the read "
                               f"face (stale locked state reported) — "
                               f"Type4_StateLogicViolation")
        else:
            NOTES.append(f"release POST answered {sr} — released-state "
                         f"reflection leg E skipped — "
                         f"raw={str(rawr)[:150]}")

        for n in NOTES:
            print(f"NOTE: {n}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("locks+get behavioral promise verified: 200 answered and the "
              "read face tracked engage / message re-set / release with no "
              "flapping across repeated reads — NO_DEFECT")
        return "NO_DEFECT"
    finally:
        # cleanup: guarded lock release (lock face via requests fallback)
        try:
            locks_http("POST", {"write": False}, timeout=10)
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
