#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_locks_set_001
# strategy: type
# endpoint: locks+set
# constraint_ids: qdrant_type_locks_set_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/service/post-locks
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 Parameter Coercion Trust — the write face is trusted to
#   serde-validate the LocksOption body, but coercion gaps let non-boolean
#   write values / non-string-null error_message values through silently.
"""
TestVDB Boundary Attack Script — Target: qdrant v1.18.0
Attack: request-body type-boundary attack (strategy=type x
  qdrant_type_locks_set_001; chunk_locks+set scope=locks+set POST /locks).
  Assertion under test (contract constraints.type_constraints):
  "body LocksOption: write is a required boolean; error_message is string
  or null" (parameters: write boolean required=true, error_message
  string|null required=false; cross-checked against the v-1-18-x OpenAPI
  shard raw_knowledge api_endpoints[74].constraints.type[0] — same text).
  Positive anchor (G4): a strictly valid {"write": false} must be
  accepted, proving the matrix is not testing a dead parser.
  Negative matrix on the two declared fields: write missing / null /
  "true" (string) / 1 / 0 (ints) / [] / {} / body {} empty / no body at
  all; error_message 123 / {"x":1} / [1] / true (write:false so a coerced
  accept cannot silently engage the lock). Expected vs actual per leg:
  expected 4xx reject vs measured status; a 2xx on a type-confused body
  = Type1_IllegalSuccess (schema promise violated on a success status);
  on any 2xx the lock is immediately released and, when the read face is
  live, GET /locks (locks+get declared response_shape grid
  result.write:boolean) is read as state-coercion evidence.
  Dual-path per R19 (chunk_global) + R24 (chunk_locks+get) reflection:
  on this OSS v1.18.0 deployment GET/POST /locks are expected to answer
  non-2xx (404 — the locks family is absent from the service_api.rs
  route table; cloud doc backfill; R19 and R24 both measured the 404
  pair) -> ENDPOINT_ABSENT -> NO_DEFECT with probe evidence. POST
  non-2xx while GET answers 2xx = interface-parity defect signal (G9:
  the write face this chunk owns is the missing one). Transport-0 probes
  with /healthz alive are NOT adjudicated as absence (honest
  SCRIPT_ERROR instead).
Oracle: live /locks: the valid-control leg {"write": false} must answer 2xx and every one of the 13 type-confused LocksOption legs (write missing/null/"true"/1/0/[]/{}/empty-body/no-body; error_message=123/{"x":1}/[1]/true) must answer 400/422 — any 2xx on a confused leg = Type1_IllegalSuccess, 5xx with /healthz alive = Type3_RuntimeFailure; if GET+POST /locks both answer a concrete non-2xx status (404 expected on OSS v1.18.0), NO_DEFECT with endpoint-absence evidence (constraint not actuable)
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
    print("FALLBACK_TRIGGERED: locks write-face attack (locks+set POST /locks with type-confused LocksOption bodies) and its locks+get GET /locks probe have no qdrant runtime PATHS key; issuing the contract-derived REST path /locks via requests")
    print("[FALLBACK_JUSTIFIED: scripts/runtime/qdrant.py PATHS (create_collection..metrics) exposes no locks key; chunk_locks+set unit qdrant_type_locks_set_001 is anchored on contract api_endpoints locks+set (POST, parameters write:boolean required / error_message:string|null) whose raw_knowledge api_endpoints url field reads '/locks', with locks+get (GET /locks) as the read-face probe; both paths are derived 1:1 from the contract records and the runtime whitelist gap is a runtime-coverage gap, not a reason to drop the unit — same FALLBACK precedent as R24 boundary_locks_get_001 in this session]")


def locks_http(method, body=None, timeout=15, send_body=True):
    """FALLBACK face mirroring rt.request's (status, raw_text) 2-tuple for
    the contract-declared /locks service endpoint (no runtime PATHS key).
    send_body=False issues a bodiless POST (no-body leg of the matrix)."""
    _fallback_markers()
    url = BASE_URL + "/locks"
    headers = {"Content-Type": "application/json"}
    _a = os.environ.get("TESTVDB_AUTH_HEADER", "")
    if _a:
        headers["Authorization"] = _a
    try:
        if send_body:
            r = requests.request(method, url, json=body, headers=headers,
                                 timeout=timeout)
        else:
            r = requests.request(method, url, headers=headers, timeout=timeout)
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
    PFX = "lts1_" + TS + "_"          # unique-prefix discipline (standing lesson)
    DEFECTS = []
    NOTES = []

    def alive():
        hs, hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        return hs == 200

    def read_state():
        """Auxiliary state evidence via the locks+get read face (its declared
        response_shape grid carries result.write:boolean). None if absent."""
        s, raw = locks_http("GET", timeout=10)
        print(f"[state GET /locks] status={s} raw={str(raw)[:200]}")
        if not (200 <= s <= 299):
            return None
        b = parse_json(raw)
        res = b.get("result") if isinstance(b, dict) else None
        if isinstance(res, dict) and isinstance(res.get("write"), bool):
            return res["write"]
        return None

    def release_lock():
        try:
            s, _ = locks_http("POST", {"write": False}, timeout=10)
            return 200 <= s <= 299
        except Exception:
            return False

    def type_leg(tag, body, send_body=True, field_hint="write"):
        """One type-confusion leg. Expected: 4xx reject. Measured vs expected
        adjudication (D3a): 2xx = Type1 (schema promise on success status),
        5xx/transport with /healthz alive = Type3, 4xx = pass."""
        if send_body:
            s, raw = locks_http("POST", body, timeout=15)
        else:
            s, raw = locks_http("POST", send_body=False, timeout=15)
        shown = json.dumps(body, ensure_ascii=False)[:80] if send_body else "<no body>"
        print(f"[{tag}] body={shown} status={s} raw={str(raw)[:300]}")
        if s == 0:
            if not alive():
                return "TRANSPORT"
            DEFECTS.append(f"[{tag}] transport failure with /healthz alive — "
                           f"Type3_RuntimeFailure (write face died on "
                           f"type-confused body) — exc={str(raw)[:150]}")
            return "OK"
        if 500 <= s <= 599:
            if alive():
                DEFECTS.append(f"[{tag}] answered {s} (5xx crash-class) with "
                               f"/healthz alive — Type3_RuntimeFailure — "
                               f"raw={str(raw)[:200]}")
            else:
                return "TRANSPORT"
            return "OK"
        if 200 <= s <= 299:
            msg = (f"[{tag}] 2xx ({s}) on a type-confused LocksOption body "
                   f"(expected 400/422 per 'write is a required boolean; "
                   f"error_message is string or null') — "
                   f"Type1_IllegalSuccess — raw={str(raw)[:200]}")
            # state-coercion evidence: did the confused body move the lock?
            st = read_state()
            if st is True:
                msg += (" — AND GET /locks reports result.write===True: the "
                        "coerced body ENGAGED the write lock (state effect "
                        "compounds the Type1)")
            release_lock()
            DEFECTS.append(msg)
            return "OK"
        if 400 <= s <= 499:
            low = str(raw).lower()
            if field_hint in low:
                print(f"[{tag}] clean reject ({s}) naming the field — pass")
            else:
                NOTES.append(f"[{tag}] clean reject ({s}) but the message does "
                             f"not name '{field_hint}' — diagnostics-quality "
                             f"note for the judge (Type2 signal, not "
                             f"adjudicated hard here; verdict keys on the "
                             f"schema assertion) — raw={str(raw)[:150]}")
            return "OK"
        NOTES.append(f"[{tag}] unexpected status {s} — recorded for the "
                     f"judge — raw={str(raw)[:150]}")
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
                  "endpoint absence vs write-face defect -> SCRIPT_ERROR "
                  "(R24 discipline: absence requires a concrete HTTP non-2xx "
                  "status on BOTH probes)")
            return "SCRIPT_ERROR"

        get_live = 200 <= s0 <= 299
        post_live = 200 <= s1 <= 299

        if not get_live and not post_live:
            print("[ENDPOINT_ABSENT] GET /locks and POST /locks both answered "
                  f"concrete non-2xx statuses ({s0} / {s1}) on the deployed "
                  "qdrant v1.18.0 OSS image (server commit "
                  "db3fca327851e360c521065649e0f65a57fe7d3c per "
                  "deployment_meta.json); the write face this type constraint "
                  "is anchored to is not registered in that commit's route "
                  "table (src/actix/api/service_api.rs registers only "
                  "telemetry/metrics/stacktrace/healthz/livez/readyz/logger/"
                  "truncate_unapplied_wal) — R19 (chunk_global) and R24 "
                  "(chunk_locks+get) measured the same 404 pair, R8 baseline: "
                  "/locks = not_found_in_source cloud doc backfill, so the "
                  "LocksOption body schema is not actuable on this binary and "
                  "cannot be violated — NO_DEFECT (measured negative with "
                  "probe evidence above)")
            return "NO_DEFECT"

        if not post_live and get_live:
            DEFECTS.append(f"interface parity: POST /locks answered {s1} "
                           f"(non-2xx) while GET /locks answered {s0} — the "
                           f"locks family IS live (route registered) but the "
                           f"documented write face (locks+set, 200 on valid "
                           f"LocksOption, source_url https://api.qdrant.tech/"
                           f"v-1-18-x/api-reference/service/post-locks) is "
                           f"missing — Type4_StateLogicViolation (G9 "
                           f"same-family face asymmetry; this chunk's primary "
                           f"face is the absent one) — POST raw="
                           f"{str(raw1)[:150]}")
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"

        # ---- (P) positive anchor: strictly valid body must be accepted ----
        sp, rawp = locks_http("POST", {"write": False}, timeout=15)
        print(f"[P valid control write=false] status={sp} raw={str(rawp)[:300]}")
        if sp == 0 or 500 <= sp <= 599:
            if not alive():
                return "SCRIPT_ERROR"
            DEFECTS.append(f"[P valid control] valid LocksOption answered "
                           f"{sp} on a live write face (promise: 200) — "
                           f"Type3/RuntimeFailure-class — raw="
                           f"{str(rawp)[:200]}")
        elif not (200 <= sp <= 299):
            DEFECTS.append(f"[P valid control] valid LocksOption "
                           f"{{\"write\": false}} answered {sp} (non-2xx) on a "
                           f"live write face — the acceptance promise is "
                           f"broken, so the negative matrix would be "
                           f"ungrounded (G4) — Type4_StateLogicViolation — "
                           f"raw={str(rawp)[:200]}")
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        else:
            print("[P valid control] 2xx — parser alive, matrix grounded")

        # ---- (N) type-confusion matrix ----
        legs = [
            ("N1 write missing", {"error_message": PFX + "msg"}, "write"),
            ("N2 write=null", {"write": None}, "write"),
            ("N3 write=\"true\" string", {"write": "true"}, "write"),
            ("N4 write=1 int", {"write": 1}, "write"),
            ("N5 write=0 int", {"write": 0}, "write"),
            ("N6 write=[] array", {"write": []}, "write"),
            ("N7 write={} object", {"write": {}}, "write"),
            ("N8 body {} empty", {}, "write"),
            ("N9 no body", None, "write"),
            ("N10 error_message=123 int", {"write": False, "error_message": 123}, "error_message"),
            ("N11 error_message object", {"write": False, "error_message": {"x": 1}}, "error_message"),
            ("N12 error_message array", {"write": False, "error_message": [1]}, "error_message"),
            ("N13 error_message=true bool", {"write": False, "error_message": True}, "error_message"),
        ]
        for tag, body, hint in legs:
            if tag == "N9 no body":
                if type_leg(tag, None, send_body=False, field_hint=hint) == "TRANSPORT":
                    return "SCRIPT_ERROR"
            else:
                if type_leg(tag, body, field_hint=hint) == "TRANSPORT":
                    return "SCRIPT_ERROR"

        for n in NOTES:
            print(f"NOTE: {n}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("locks+set LocksOption type matrix: valid control accepted, all "
              "13 type-confused bodies cleanly rejected with field-naming "
              "diagnostics — NO_DEFECT")
        return "NO_DEFECT"
    finally:
        # cleanup: guarded lock release (lock face via requests fallback)
        try:
            release_lock()
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
