#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_locks_get_001
# strategy: type
# endpoint: locks+get
# constraint_ids: qdrant_type_locks_get_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/service/get-locks
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01-adjacent response-shape trust — the request-side coercion
#   gap has no surface on GET /locks (contract api_endpoints declares no body
#   params, only the optional api-key header), so the type attack targets the
#   RESPONSE side: does the serde'd LocksOption actually conform to the
#   published response_shape grid in every reachable state.
"""
TestVDB Boundary Attack Script — Target: qdrant v1.18.0
Attack: response-shape type-boundary attack (strategy=type x
  qdrant_type_locks_get_001; chunk_locks+get scope=locks+get GET /locks).
  Assertion under test: the locks+get response is a LocksOption conforming
  to the contract response_shape grid {time: number, status: string,
  result: object, result.write: boolean, result.error_message:
  string|null} (grid cross-checked against the v-1-18-x OpenAPI shard
  api-reference-*.json per standing lesson). State driver: POST /locks
  (locks+set) used ONLY as actuator to move the read face between states
  — its own faces belong to chunk_locks+set, not adjudicated here.
  Legs: (0) GET+POST /locks probes; (A) baseline GET strict grid check —
  result.write must be a JSON boolean (not "true"/1), result.error_message
  key present with string-or-null value (not object/array), envelope
  time:number / status:string; (B) engage write=true + unique
  error_message token -> GET grid check with write===True, then 5
  repeated GETs all grid-conformant (shape stability, no flapping);
  (C) release write=false -> GET grid check with write===False.
  Dual-path per R19 (chunk_global) reflection: on this OSS v1.18.0
  deployment GET/POST /locks are expected to answer non-2xx (404 — the
  locks family is absent from the service_api.rs route table; cloud
  doc backfill) -> ENDPOINT_ABSENT -> NO_DEFECT with probe evidence
  (R19/R8 baseline disposition). GET non-2xx while POST answers 2xx =
  interface-parity defect signal (G9: read face documented 200 missing
  while the family is live). Transport-0 probes with /healthz alive are
  NOT adjudicated as absence (honest SCRIPT_ERROR instead).
Oracle: live /locks: every 200 body must satisfy the full grid — time number, status string, result object, result.write present and JSON boolean, result.error_message present and string-or-null — in baseline, locked (write===True, incl. 5 repeated GETs) and released (write===False) states; any 200 deviating from the grid = Type1_IllegalSuccess (shape violation on a success status); 5xx on a live GET with /healthz alive = Type3_RuntimeFailure; if GET+POST /locks both answer a concrete non-2xx status (404 expected on OSS v1.18.0), NO_DEFECT with endpoint-absence evidence (constraint not actuable)
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
    print("[FALLBACK_JUSTIFIED: scripts/runtime/qdrant.py PATHS (create_collection..metrics) exposes no locks key; chunk_locks+get unit qdrant_type_locks_get_001 is anchored on contract api_endpoints locks+get (GET, response_shape time/status/result/result.write/result.error_message) whose raw_knowledge api_endpoints url field reads '/locks', with locks+set (POST /locks, required body field write) as the only state actuator; both paths are derived 1:1 from the contract records and the runtime whitelist gap is a runtime-coverage gap, not a reason to drop the unit — same FALLBACK precedent as state_global_001 in this session]")


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


def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def grid_violations(raw, expect_write=None):
    """Strict response_shape-grid check for one 200 body of GET /locks.
    Grid: time:number, status:string, result:object, result.write:boolean,
    result.error_message:string|null (contract api_endpoints[locks+get]
    .response_shape, cross-checked against v-1-18-x OpenAPI shard)."""
    v = []
    b = parse_json(raw)
    if b is None:
        return ["200 body is not a JSON object — grid unusable"]
    if not is_number(b.get("time")):
        v.append(f"time={b.get('time')!r} ({type(b.get('time')).__name__}) — grid: number")
    if not isinstance(b.get("status"), str):
        v.append(f"status={b.get('status')!r} ({type(b.get('status')).__name__}) — grid: string")
    res = b.get("result")
    if not isinstance(res, dict):
        v.append(f"result={res!r} ({type(res).__name__}) — grid: object")
        return v
    if "write" not in res:
        v.append("result.write key MISSING — grid: boolean")
    else:
        w = res["write"]
        if not isinstance(w, bool):
            v.append(f"result.write={w!r} ({type(w).__name__}) — grid: boolean (strict, not \"true\"/1)")
        elif expect_write is not None and w is not expect_write:
            v.append(f"result.write={w!r}, expected {expect_write!r} for the actuated state")
    if "error_message" not in res:
        v.append("result.error_message key MISSING — grid: string|null")
    else:
        em = res["error_message"]
        if not (em is None or isinstance(em, str)):
            v.append(f"result.error_message={em!r} ({type(em).__name__}) — grid: string|null")
    return v


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "lgt1_" + TS + "_"          # unique-prefix discipline (standing lesson)
    TOKEN = PFX + "shapemsg"
    DEFECTS = []
    NOTES = []

    def alive():
        hs, hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        return hs == 200

    def live_get_leg(tag, expect_write=None):
        """One live GET /locks read: 200 -> grid check; 5xx -> Type3 (with
        liveness re-check); other non-2xx -> promise-flap note->defect."""
        s, raw = locks_http("GET", timeout=15)
        print(f"[{tag}] status={s} raw={str(raw)[:300]}")
        if s == 0:
            if not alive():
                return "TRANSPORT"
            DEFECTS.append(f"[{tag}] GET /locks transport failure with "
                           f"/healthz alive — Type3_RuntimeFailure")
            return "OK"
        if 500 <= s <= 599:
            if alive():
                DEFECTS.append(f"[{tag}] GET /locks returned {s} (5xx on the "
                               f"read face) with /healthz alive — "
                               f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
            else:
                return "TRANSPORT"
            return "OK"
        if not (200 <= s <= 299):
            DEFECTS.append(f"[{tag}] GET /locks flapped to {s} after the "
                           f"probe already answered 2xx — read-face 200 "
                           f"promise broken — Type4_StateLogicViolation — "
                           f"raw={str(raw)[:150]}")
            return "OK"
        viol = grid_violations(raw, expect_write=expect_write)
        if viol:
            for x in viol:
                DEFECTS.append(f"[{tag}] 200 body violates response_shape "
                               f"grid — Type1_IllegalSuccess (shape violation "
                               f"on success status) — {x} — raw={str(raw)[:200]}")
        else:
            b = parse_json(raw)
            res = b.get("result") if isinstance(b, dict) else None
            print(f"[{tag}] grid-conformant (result.write="
                  f"{res.get('write')!r}, result.error_message="
                  f"{res.get('error_message')!r})")
        return "OK"

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
                  "deployment_meta.json); the locks family this type "
                  "constraint is anchored to is not registered in that "
                  "commit's route table (src/actix/api/service_api.rs "
                  "registers only telemetry/metrics/stacktrace/healthz/"
                  "livez/readyz/logger/truncate_unapplied_wal) — R19 "
                  "(chunk_global) measured the same 404 pair, R8 baseline: "
                  "/locks = not_found_in_source cloud doc backfill, so the "
                  "LocksOption response_shape grid is not actuable on this "
                  "binary and cannot be violated — NO_DEFECT (measured "
                  "negative with probe evidence above)")
            return "NO_DEFECT"

        if not get_live and post_live:
            DEFECTS.append(f"interface parity: GET /locks answered {s0} "
                           f"(non-2xx) while POST /locks answered {s1} — the "
                           f"locks family IS live (route registered) but the "
                           f"documented read face (200 + LocksOption shape, "
                           f"source_url https://api.qdrant.tech/v-1-18-x/"
                           f"api-reference/service/get-locks) is missing — "
                           f"Type4_StateLogicViolation (G9 same-family face "
                           f"asymmetry; judge: contradicting the doc's "
                           f"GET-face 200 promise) — GET raw={str(raw0)[:150]}")
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"

        if not post_live:
            NOTES.append(f"POST /locks actuator probe answered {s1} while GET "
                         f"is live — state-driving unavailable (locks+set "
                         f"faces belong to chunk_locks+set); running baseline "
                         f"grid + stability legs only")

        # ---- (A) baseline grid check ----
        if live_get_leg("A baseline grid") == "TRANSPORT":
            return "SCRIPT_ERROR"

        # ---- (B) engaged state: grid + strict boolean + stability ----
        if post_live:
            se, rawe = locks_http("POST", {"write": True,
                                           "error_message": TOKEN}, timeout=15)
            print(f"[engage write=true token={TOKEN}] status={se} "
                  f"raw={str(rawe)[:300]}")
            if not (200 <= se <= 299):
                NOTES.append(f"engage POST answered {se} after a 2xx probe — "
                             f"skipping engaged/released legs (actuator face "
                             f"out of this chunk's scope) — raw={str(rawe)[:150]}")
            else:
                if live_get_leg("B locked grid", expect_write=True) == "TRANSPORT":
                    return "SCRIPT_ERROR"
                for i in range(5):
                    if live_get_leg(f"B stability #{i + 1}",
                                    expect_write=True) == "TRANSPORT":
                        return "SCRIPT_ERROR"
                # (exact error_message echo is behavioral currency — script
                #  boundary_locks_get_002 adjudicates it; here only its TYPE
                #  was checked inside the grid.)

        # ---- (C) released state: grid + strict boolean False ----
        if post_live:
            sr, rawr = locks_http("POST", {"write": False}, timeout=15)
            print(f"[release write=false] status={sr} raw={str(rawr)[:300]}")
            if 200 <= sr <= 299:
                if live_get_leg("C released grid", expect_write=False) == "TRANSPORT":
                    return "SCRIPT_ERROR"
            else:
                NOTES.append(f"release POST answered {sr} — released-state "
                             f"grid leg skipped — raw={str(rawr)[:150]}")

        for n in NOTES:
            print(f"NOTE: {n}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("locks+get response-shape grid verified conformant in every "
              "actuated state (strict boolean write, string|null "
              "error_message, envelope types) — NO_DEFECT")
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
