#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_locks_get_003
# strategy: malformed_input
# endpoint: locks+get
# constraint_ids: qdrant_behavioral_locks_get_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/service/get-locks
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 request-parsing trust — GET /locks declares no request
#   parameters (only an optional api-key header), so the parser is trusted
#   with ANY stream shape; adversarial query strings / unexpected bodies /
#   malformed encodings probe whether the read face degrades gracefully
#   (G5: crash-class failure is the defect, clean 4xx is not).
"""
TestVDB Boundary Attack Script — Target: qdrant v1.18.0
Attack: malformed-input / robustness attack on the locks read face
  (strategy=malformed_input x qdrant_behavioral_locks_get_001;
  chunk_locks+get scope=locks+get GET /locks). The assertion promises
  "HTTP 200 with {write: bool, error_message: string|null}" on a face
  that declares NO request parameters — the negative construction (G4)
  is adversarial request material the doc never anticipated: junk query
  params (type-confused write=banana, boundary junk limit=-1 /
  offset=1e20), malformed percent-encoding (%zz), a truncated-JSON body
  and a NUL-led binary body on a GET, and a 10k-char overlong query
  value. Graceful-degradation typing (G5): 200 with a grid-conformant
  LocksOption (junk ignored, promise kept) or a clean 4xx (defensive
  reject) = not a defect; 5xx / transport death with /healthz alive =
  Type3_RuntimeFailure (crash-class). This is the implementation-limit
  class (strategy 7), NOT the contract-boundary class: acceptance is
  legal, crash is the defect. Dual-path per R19 (chunk_global)
  reflection: both /locks probes concrete non-2xx (404 expected on this
  OSS v1.18.0 image — locks family absent from the service_api.rs route
  table, cloud doc backfill) -> ENDPOINT_ABSENT -> NO_DEFECT with probe
  evidence (R19/R8 baseline); GET non-2xx while POST 2xx =
  interface-parity defect (G9); transport-0 probes with /healthz alive
  are NOT adjudicated as absence (honest SCRIPT_ERROR).
Oracle: live /locks: each of the 6 malformed-input probes (junk typed params, boundary junk, %zz encoding, truncated-JSON body, NUL binary body, 10k overlong value) must answer either 200 with a grid-conformant LocksOption (result.write boolean, result.error_message string|null — junk ignored) or a clean 4xx; any 5xx or transport failure with /healthz alive = Type3_RuntimeFailure (parser/handler crash on the read face); if GET+POST /locks both answer concrete non-2xx (404 expected on OSS v1.18.0), NO_DEFECT with endpoint-absence evidence (face not actuable)
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
    print("FALLBACK_TRIGGERED: locks read-face probes (locks+get GET /locks with adversarial query/body material, locks+set POST /locks probe) have no qdrant runtime PATHS key; issuing the contract-derived REST path /locks via requests with raw query/data parameters")
    print("[FALLBACK_JUSTIFIED: scripts/runtime/qdrant.py PATHS (create_collection..metrics) exposes no locks key and its request() signature takes no raw query-string/data passthrough — malformed percent-encoding (%zz), raw NUL-led bodies and prebuilt query strings cannot be forwarded through the runtime wrapper at all; chunk_locks+get unit qdrant_behavioral_locks_get_001 is anchored on contract api_endpoints locks+get whose raw_knowledge api_endpoints url field reads '/locks' (expected_responses 200=LocksOption{write,error_message}); the path is derived 1:1 from the contract record and the runtime whitelist gap plus its no-raw-passthrough signature make requests the only faithful carrier for this malformed-input probe — same FALLBACK precedent as state_global_001 in this session]")


def locks_http_raw(method="GET", body=None, timeout=15, raw_query=None,
                   data=None, content_type=None):
    """FALLBACK face for the contract-declared /locks endpoint, extended
    with raw query-string / raw body passthrough (malformed material must
    bypass client JSON serialization — strategy 7 safety wrapper).
    Returns (status, raw_text) mirroring rt.request's 2-tuple."""
    _fallback_markers()
    url = BASE_URL + "/locks"
    if raw_query:
        url = url + "?" + raw_query
    headers = {}
    if content_type:
        headers["Content-Type"] = content_type
    elif body is not None:
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
    PFX = "lgm1_" + TS + "_"          # unique-prefix discipline (standing lesson)
    DEFECTS = []
    NOTES = []

    def alive():
        hs, hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        return hs == 200

    def shape_ok(raw):
        """Light grid check for a 200 answer: result object, write boolean,
        error_message string|null (full strict grid is script
        boundary_locks_get_001's assertion; here it only guards that a
        200 'junk-ignored' answer still carries the promised state)."""
        b = parse_json(raw)
        if not isinstance(b, dict):
            return False, "200 body is not a JSON object"
        res = b.get("result")
        if not isinstance(res, dict):
            return False, "result is not an object"
        w = res.get("write")
        if not isinstance(w, bool):
            return False, f"result.write={w!r} is not a boolean"
        em = res.get("error_message")
        if not (em is None or isinstance(em, str)):
            return False, f"result.error_message={em!r} is not string|null"
        return True, (f"write={w!r}, error_message={em!r}")

    def probe_leg(tag, **kw):
        """One malformed-input probe on GET /locks with graceful-degradation
        typing: 200+shape or clean 4xx = pass; 5xx/transport+alive = Type3."""
        s, raw = locks_http_raw("GET", timeout=15, **kw)
        print(f"[{tag}] status={s} raw={str(raw)[:300]}")
        if s == 0:
            if not alive():
                return "TRANSPORT"
            DEFECTS.append(f"[{tag}] transport failure with /healthz alive — "
                           f"Type3_RuntimeFailure (read face died on "
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
            ok, info = shape_ok(raw)
            if ok:
                print(f"[{tag}] junk ignored — 200 with promised state "
                      f"({info})")
            else:
                DEFECTS.append(f"[{tag}] answered 200 but the body does not "
                               f"carry the promised LocksOption state ({info}) "
                               f"— Type1_IllegalSuccess — "
                               f"raw={str(raw)[:200]}")
        elif 400 <= s <= 499:
            print(f"[{tag}] clean defensive rejection ({s}) — not a defect "
                  f"(graceful degradation)")
        else:
            NOTES.append(f"[{tag}] unexpected status {s} (neither 2xx/4xx/5xx)"
                         f" — recorded for the judge — raw={str(raw)[:150]}")
        return "OK"

    try:
        # ---- (0) endpoint probes (GET read face + POST hygiene release) ----
        s0, raw0 = locks_http_raw("GET", timeout=10)
        print(f"[probe GET /locks] status={s0} raw={str(raw0)[:300]}")
        s1, raw1 = locks_http_raw("POST", body={"write": False}, timeout=10)
        print(f"[probe POST /locks write=false] status={s1} "
              f"raw={str(raw1)[:300]}")

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
                  "deployment_meta.json); the locks read face this "
                  "malformed-input probe targets is not registered in that "
                  "commit's route table (src/actix/api/service_api.rs "
                  "registers only telemetry/metrics/stacktrace/healthz/"
                  "livez/readyz/logger/truncate_unapplied_wal) — R19 "
                  "(chunk_global) measured the same 404 pair, R8 baseline: "
                  "/locks = not_found_in_source cloud doc backfill, so there "
                  "is no live handler to crash and the probe is not actuable "
                  "on this binary — NO_DEFECT (measured negative with probe "
                  "evidence above)")
            return "NO_DEFECT"

        if not get_live and post_live:
            DEFECTS.append(f"interface parity: GET /locks answered {s0} "
                           f"(non-2xx) while POST /locks answered {s1} — the "
                           f"locks family IS live (route registered) but the "
                           f"documented read face (200 + LocksOption state, "
                           f"source_url https://api.qdrant.tech/v-1-18-x/"
                           f"api-reference/service/get-locks) is missing — "
                           f"Type4_StateLogicViolation (G9 same-family face "
                           f"asymmetry) — GET raw={str(raw0)[:150]}")
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"

        # ---- malformed-input matrix on the live read face ----
        legs = [
            ("L1 junk typed params",
             dict(raw_query="write=banana&error_message=7&timeout=null")),
            ("L2 boundary junk params",
             dict(raw_query="limit=-1&offset=99999999999999999999&wait=x")),
            ("L3 malformed percent-encoding",
             dict(raw_query="%zz=1&ok=%EE")),
            ("L4 truncated-JSON body on GET",
             dict(data=b'{"write": ', content_type="application/json")),
            ("L5 NUL-led binary body on GET",
             dict(data=b"\x00\x01\x02junk\xff", content_type="application/octet-stream")),
            ("L6 overlong query value 10k",
             dict(raw_query="junk=" + "a" * 10000)),
        ]
        for tag, kw in legs:
            if probe_leg(tag, **kw) == "TRANSPORT":
                return "SCRIPT_ERROR"

        # post-matrix liveness: the read face must still answer normally
        s, raw = locks_http_raw("GET", timeout=15)
        print(f"[post-matrix plain GET] status={s} raw={str(raw)[:300]}")
        if s == 0 or 500 <= s <= 599:
            if alive():
                DEFECTS.append(f"post-matrix plain GET answered {s} with "
                               f"/healthz alive — the malformed-input matrix "
                               f"left the read face degraded — "
                               f"Type3_RuntimeFailure")
            else:
                return "SCRIPT_ERROR"
        elif 200 <= s <= 299:
            ok, info = shape_ok(raw)
            if not ok:
                DEFECTS.append(f"post-matrix plain GET 200 body lost the "
                               f"promised shape ({info}) — "
                               f"Type1_IllegalSuccess")

        for n in NOTES:
            print(f"NOTE: {n}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("locks+get malformed-input matrix survived: every probe answered "
              "200-with-state (junk ignored) or a clean 4xx, and the plain "
              "read stayed healthy afterwards — NO_DEFECT")
        return "NO_DEFECT"
    finally:
        # cleanup: guarded lock release (lock face via requests fallback)
        try:
            locks_http_raw("POST", body={"write": False}, timeout=10)
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
