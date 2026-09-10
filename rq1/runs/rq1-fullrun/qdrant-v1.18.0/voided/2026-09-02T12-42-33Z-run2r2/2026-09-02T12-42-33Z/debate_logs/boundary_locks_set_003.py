#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_locks_set_003
# strategy: behavioral
# endpoint: locks+set
# constraint_ids: qdrant_behavioral_locks_set_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/service/post-locks
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04-adjacent write-face 200 optimism + BS-07 parser trust —
#   the doc promises "valid LocksOption body returns HTTP 200", so the
#   positive legs pin that promise while malformed-stream legs (truncated
#   JSON / NUL binary / array body / string body / 100k error_message)
#   probe whether the write face's parser degrades gracefully instead of
#   crashing (G5: crash-class is the defect, clean 4xx is not).
"""
TestVDB Boundary Attack Script — Target: qdrant v1.18.0
Attack: behavioral 200-promise + malformed-stream robustness attack
  (strategy=behavioral x qdrant_behavioral_locks_set_001;
  chunk_locks+set scope=locks+set POST /locks). Assertion under test
  (contract assertions[].expected_behavior): "valid LocksOption body
  returns HTTP 200". G4 pairing: positive legs exercise the promise on
  the three strictly-valid body shapes — {"write": false},
  {"write": true, "error_message": str} (+immediate guarded release),
  {"write": false, "error_message": null} (explicit null is legal
  string|null); a non-2xx on a live write face for any of them breaks
  the 200 promise (Type4_StateLogicViolation). Negative legs are the
  implementation-limit class (strategy-7 robustness, graceful-degradation
  typing G5): truncated JSON body, NUL-led binary body, JSON array body,
  JSON string body, 100k-char overlong error_message, and an
  unknown-extra-field body — 200 (junk ignored / extra field ignored)
  or a clean 4xx are both legal; 5xx or transport failure with
  /healthz alive = Type3_RuntimeFailure (parser/handler crash on the
  write face). The contract declares NO response_shape for locks+set,
  so no response grid is asserted (D3b: never invent a shape); where a
  malformed leg answers 2xx AND the locks+get read face is live, the
  declared result.write:boolean grid is read as state-effect evidence —
  a garbage stream that MOVES the lock state is adjudicated
  Type1_IllegalSuccess (a non-LocksOption stream was accepted and
  mutated service state). Post-matrix liveness leg: a plain valid POST
  must still answer 2xx afterwards (face not left degraded).
  Dual-path per R19 + R24 reflection: on this OSS v1.18.0 deployment
  GET/POST /locks are expected to answer non-2xx (404 — locks family
  absent from the service_api.rs route table; cloud doc backfill; R19
  and R24 both measured the 404 pair) -> ENDPOINT_ABSENT -> NO_DEFECT
  with probe evidence (the 200 promise has no live subject). POST
  non-2xx while GET 2xx = interface-parity defect signal (G9: this
  chunk's write face is the missing one). Transport-0 probes with
  /healthz alive are NOT adjudicated as absence (honest SCRIPT_ERROR).
Oracle: live /locks: each of the 3 valid bodies (write:false; write:true+error_message then released; write:false+error_message:null) must answer 2xx — any non-2xx = Type4 (200 promise broken, 5xx+alive = Type3); each of the 6 malformed-stream legs (truncated JSON, NUL binary, array body, string body, 100k error_message, unknown extra field) must answer 2xx or a clean 4xx — 5xx or transport with /healthz alive = Type3_RuntimeFailure, and a 2xx that moves result.write (read via live GET /locks) = Type1_IllegalSuccess; post-matrix valid POST still 2xx (degraded face = Type3); if GET+POST /locks both answer concrete non-2xx (404 expected on OSS v1.18.0), NO_DEFECT with endpoint-absence evidence (assertion not actuable)
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
    print("FALLBACK_TRIGGERED: locks write-face probes (locks+set POST /locks with valid and malformed-stream bodies, locks+get GET /locks state evidence) have no qdrant runtime PATHS key; issuing the contract-derived REST path /locks via requests with raw data passthrough for malformed bodies")
    print("[FALLBACK_JUSTIFIED: scripts/runtime/qdrant.py PATHS (create_collection..metrics) exposes no locks key and its request() signature takes no raw data passthrough — truncated-JSON / NUL-led binary bodies and prebuilt non-object JSON streams cannot be forwarded through the runtime wrapper at all (client json= serialization would refuse them first); chunk_locks+set unit qdrant_behavioral_locks_set_001 is anchored on contract api_endpoints locks+set (POST, expected_behavior 'valid LocksOption body returns HTTP 200') whose raw_knowledge api_endpoints url field reads '/locks'; the path is derived 1:1 from the contract record and the runtime whitelist gap plus its no-raw-passthrough signature make requests the only faithful carrier for this probe — same FALLBACK precedent as R24 boundary_locks_get_003 in this session]")


def locks_http_raw(method="POST", body=None, timeout=15, data=None,
                   content_type=None):
    """FALLBACK face for the contract-declared /locks endpoint, extended
    with raw body passthrough (malformed material must bypass client JSON
    serialization — strategy-7 safety wrapper). Returns (status, raw_text)
    mirroring rt.request's 2-tuple."""
    _fallback_markers()
    url = BASE_URL + "/locks"
    headers = {}
    if content_type:
        headers["Content-Type"] = content_type
    elif body is not None or data is not None:
        headers["Content-Type"] = "application/json"
    _a = os.environ.get("TESTVDB_AUTH_HEADER", "")
    if _a:
        headers["Authorization"] = _a
    try:
        r = requests.request(method, url, json=body if data is None else None,
                             data=data, headers=headers, timeout=timeout)
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
    PFX = "lbh3_" + TS + "_"          # unique-prefix discipline (standing lesson)
    DEFECTS = []
    NOTES = []

    def alive():
        hs, hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        return hs == 200

    def read_write_state():
        """State evidence via the locks+get read face (its declared
        response_shape carries result.write:boolean). None if unreadable."""
        s, raw = locks_http_raw("GET", timeout=10)
        if not (200 <= s <= 299):
            return None
        b = parse_json(raw)
        res = b.get("result") if isinstance(b, dict) else None
        if isinstance(res, dict) and isinstance(res.get("write"), bool):
            return res["write"]
        return None

    def release_lock():
        try:
            s, _ = locks_http_raw("POST", body={"write": False}, timeout=10)
            return 200 <= s <= 299
        except Exception:
            return False

    def valid_leg(tag, body):
        """One strictly-valid LocksOption body. Expected: 2xx (the 200
        promise). Measured deviations: non-2xx on a live face = Type4
        (promise broken); 5xx+alive = Type3; transport+alive = Type3."""
        s, raw = locks_http_raw("POST", body=body, timeout=15)
        print(f"[{tag}] body={json.dumps(body)[:80]} status={s} "
              f"raw={str(raw)[:300]}")
        if s == 0:
            if not alive():
                return "TRANSPORT"
            DEFECTS.append(f"[{tag}] valid LocksOption transport failure "
                           f"with /healthz alive — Type3_RuntimeFailure — "
                           f"exc={str(raw)[:150]}")
            return "OK"
        if 500 <= s <= 599:
            if alive():
                DEFECTS.append(f"[{tag}] valid LocksOption answered {s} "
                               f"(5xx crash-class) with /healthz alive — "
                               f"the 200 promise broke as a runtime failure "
                               f"— Type3_RuntimeFailure — "
                               f"raw={str(raw)[:200]}")
            else:
                return "TRANSPORT"
            return "OK"
        if not (200 <= s <= 299):
            DEFECTS.append(f"[{tag}] valid LocksOption answered {s} "
                           f"(non-2xx) on a live write face — expected 200 "
                           f"per the assertion under test — "
                           f"Type4_StateLogicViolation — "
                           f"raw={str(raw)[:200]}")
            return "OK"
        print(f"[{tag}] 200 promise kept")
        return "OK"

    def malformed_leg(tag, **kw):
        """One malformed-stream probe with graceful-degradation typing
        (G5): 2xx (junk ignored) or clean 4xx = pass; 5xx/transport with
        /healthz alive = Type3; a 2xx that MOVES the lock state (read via
        live GET) = Type1 (state effect from a non-LocksOption stream)."""
        s, raw = locks_http_raw("POST", timeout=15, **kw)
        print(f"[{tag}] status={s} raw={str(raw)[:300]}")
        if s == 0:
            if not alive():
                return "TRANSPORT"
            DEFECTS.append(f"[{tag}] transport failure with /healthz alive — "
                           f"Type3_RuntimeFailure (write-face parser died on "
                           f"malformed input) — exc={str(raw)[:150]}")
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
            st = read_write_state()
            if st is True:
                DEFECTS.append(f"[{tag}] answered 200 on a malformed stream "
                               f"AND GET /locks reports result.write===True — "
                               f"a non-LocksOption stream moved the lock "
                               f"state — Type1_IllegalSuccess — "
                               f"raw={str(raw)[:200]}")
                release_lock()
            else:
                print(f"[{tag}] 200 with junk ignored (state evidence: "
                      f"{st!r}) — legal graceful degradation")
        elif 400 <= s <= 499:
            print(f"[{tag}] clean defensive rejection ({s}) — not a defect "
                  f"(graceful degradation)")
        else:
            NOTES.append(f"[{tag}] unexpected status {s} — recorded for the "
                         f"judge — raw={str(raw)[:150]}")
        return "OK"

    try:
        # ---- (0) endpoint probes (GET read face + POST hygiene release) ----
        s0, raw0 = locks_http_raw("GET", timeout=10)
        print(f"[probe GET /locks] status={s0} raw={str(raw0)[:300]}")
        s1, raw1 = locks_http_raw("POST", body={"write": False}, timeout=10)
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
                  "deployment_meta.json); the write face whose 200 promise "
                  "this behavioral assertion is anchored to is not registered "
                  "in that commit's route table (src/actix/api/"
                  "service_api.rs registers only telemetry/metrics/"
                  "stacktrace/healthz/livez/readyz/logger/"
                  "truncate_unapplied_wal) — R19 (chunk_global) and R24 "
                  "(chunk_locks+get) measured the same 404 pair, R8 "
                  "baseline: /locks = not_found_in_source cloud doc "
                  "backfill, so there is no live handler whose 200 promise "
                  "could be kept or broken — NO_DEFECT (measured negative "
                  "with probe evidence above)")
            return "NO_DEFECT"

        if not post_live and get_live:
            DEFECTS.append(f"interface parity: POST /locks answered {s1} "
                           f"(non-2xx) while GET /locks answered {s0} — the "
                           f"locks family IS live (route registered) but the "
                           f"documented write face ('valid LocksOption body "
                           f"returns HTTP 200', source_url https://"
                           f"api.qdrant.tech/v-1-18-x/api-reference/service/"
                           f"post-locks) is missing — "
                           f"Type4_StateLogicViolation (G9 same-family face "
                           f"asymmetry; this chunk's primary face is the "
                           f"absent one) — POST raw={str(raw1)[:150]}")
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"

        # ---- (P) positive legs: the three strictly-valid body shapes ----
        for tag, body in [
            ("P1 write=false", {"write": False}),
            ("P2 write=true+msg then release", {"write": True,
                                                "error_message": PFX + "msg"}),
            ("P3 write=false+null msg", {"write": False, "error_message": None}),
        ]:
            if valid_leg(tag, body) == "TRANSPORT":
                return "SCRIPT_ERROR"
            if tag.startswith("P2"):
                release_lock()  # never leave the write lock engaged

        # ---- (M) malformed-stream matrix on the live write face ----
        legs = [
            ("M1 truncated-JSON body",
             dict(data=b'{"write": ', content_type="application/json")),
            ("M2 NUL-led binary body",
             dict(data=b"\x00\x01\x02junk\xff", content_type="application/octet-stream")),
            ("M3 JSON array body", dict(data=b'[true]')),
            ("M4 JSON string body", dict(data=b'"write"')),
            ("M5 overlong error_message 100k",
             dict(body={"write": False, "error_message": "a" * 100000})),
            ("M6 unknown extra field",
             dict(body={"write": False, PFX + "junk_field": 123})),
        ]
        for tag, kw in legs:
            if malformed_leg(tag, **kw) == "TRANSPORT":
                return "SCRIPT_ERROR"

        # ---- (L) post-matrix liveness: the promise must still hold ----
        s, raw = locks_http_raw("POST", body={"write": False}, timeout=15)
        print(f"[post-matrix valid POST] status={s} raw={str(raw)[:300]}")
        if s == 0 or 500 <= s <= 599:
            if alive():
                DEFECTS.append(f"post-matrix valid POST answered {s} with "
                               f"/healthz alive — the malformed-stream matrix "
                               f"left the write face degraded — "
                               f"Type3_RuntimeFailure")
            else:
                return "SCRIPT_ERROR"
        elif not (200 <= s <= 299):
            DEFECTS.append(f"post-matrix valid POST answered {s} (non-2xx) "
                           f"after the matrix — the 200 promise no longer "
                           f"holds on a live face — "
                           f"Type4_StateLogicViolation")

        for n in NOTES:
            print(f"NOTE: {n}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("locks+set write face: 200 promise kept on all three valid "
              "bodies, malformed-stream matrix survived (junk ignored or "
              "cleanly rejected, state never moved by garbage), face healthy "
              "afterwards — NO_DEFECT")
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
