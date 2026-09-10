#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_metrics_002
# strategy: behavioral
# endpoint: metrics
# constraint_ids: qdrant_behavioral_metrics_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/service/metrics
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-02-adjacent (envelope/diagnostic negligence on a telemetry
#   face) — the assertion pins not just the body but the explicit
#   "content-type text/plain" response header; the runtime wrapper returns
#   only (status, text) and would silently drop the header dimension of the
#   promise, so this script carries a declared requests fallback face whose
#   only job is header capture (FALLBACK_TRIGGERED/JUSTIFIED pair printed).
"""
TestVDB Boundary Attack Script — Target: qdrant v1.18.0
Attack: behavioral content-type/format identity x
  qdrant_behavioral_metrics_001 (chunk_metrics scope = metrics GET /metrics).
  The assertion under test pins TWO observable properties: "HTTP 200 with
  text/plain Prometheus metrics body" — i.e. (a) the response Content-Type
  header must be text/plain (any Prometheus exposition parameters such as
  version=0.0.4/charset are legal suffixes), and (b) the body must be
  Prometheus exposition text, NOT JSON. Runtime-face baseline first via
  safe_request("GET","metrics") to prove the endpoint live (standing lesson:
  /metrics IS in the v1.18.0 service_api.rs route table, unlike /locks);
  then the header legs run on a declared requests fallback because
  scripts/runtime/_common.req returns (status, raw_text) only — response
  headers are unreachable through the runtime wrapper, and this unit's
  promise names the header explicitly. Legs: H1 bare (header+body identity),
  H2 Accept: application/json (content negotiation must NOT switch the
  documented text/plain format — the promise is unconditional), H3 Accept:
  text/html (same), H4 Accept: */* explicit (header+body identity re-pin).
  Every 200 leg must ALSO still parse as Prometheus text (>=1 HELP/TYPE +
  >=1 sample). Defect typing: 200 + Content-Type not starting text/plain =
  Type4_StateLogicViolation (content-type promise broken, actual header
  printed); 200 + text/plain but JSON-parseable body = Type4 (format
  promise); non-2xx on a live face = Type4 (200 promise broken);
  5xx/transport with /healthz alive = Type3_RuntimeFailure; 401/403 =
  auth-gated config -> SCRIPT_ERROR; concrete 404 with healthz 200 =
  endpoint-absent evidence -> NO_DEFECT (assertion not actuable).
Oracle: baseline runtime GET /metrics answers 200 Prometheus text, and all 4 header legs (bare, Accept: application/json, Accept: text/html, Accept: */*) answer HTTP 200 with Content-Type starting "text/plain" (parameters/charset allowed) AND a body parsing as Prometheus text (>=1 HELP/TYPE and >=1 sample) and NOT parsing as a JSON object/array — any 200 leg with a non-text/plain Content-Type = DEFECT Type4_StateLogicViolation (content-type promise broken, actual header printed), any 200 leg with JSON/shapeless body = DEFECT Type4 (format promise), non-2xx leg on the live face = DEFECT Type4 (200 promise), 5xx/transport with /healthz alive = DEFECT Type3_RuntimeFailure, 401/403 = SCRIPT_ERROR, baseline 404 + healthz 200 = NO_DEFECT endpoint-absence evidence
"""
import os
import sys
import json
import re
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
if os.environ.get("TESTVDB_TARGET", "").lower() != "qdrant":
    print(f"VERDICT: SCRIPT_ERROR - contract target mismatch (expected qdrant, got {os.environ.get('TESTVDB_TARGET')!r})")
    sys.exit(2)

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

import requests  # noqa: E402  (declared fallback face for header capture only)

# metrics is a NATIVE rt.PATHS key; cross-check against raw_knowledge
# api_endpoints[metrics].url (standing lesson: URLs from raw_knowledge
# api_endpoints[].url only). The fallback face reuses this exact URL.
METRICS_KEY = "metrics"
METRICS_URL = rt.PATHS.get(METRICS_KEY)
_derived = "runtime PATHS native entry"
for _p in Path(__file__).resolve().parents:
    _rk = _p / "raw_knowledge.json"
    if _rk.exists():
        try:
            _rkd = json.loads(_rk.read_text(encoding="utf-8"))
            for _e in _rkd.get("api_endpoints", []):
                if _e.get("path") == "metrics" and _e.get("url"):
                    if METRICS_URL != _e["url"]:
                        print(f"VERDICT: SCRIPT_ERROR - rt.PATHS[{METRICS_KEY}]="
                              f"{METRICS_URL!r} != raw_knowledge url {_e['url']!r}")
                        sys.exit(2)
                    _derived = (f"rt.PATHS == raw_knowledge api_endpoints"
                                f"[metrics].url ({_e['url']!r}) — fallback "
                                f"face reuses it verbatim")
        except Exception:
            pass
        break
print(f"[path derivation] {METRICS_KEY} = {METRICS_URL} ({_derived})")

_SAMPLE_RE = re.compile(
    r"^[a-zA-Z_:][a-zA-Z0-9_:]*(\{[^}]*\})?\s+"
    r"([-+]?(\d+\.?\d*([eE][-+]?\d+)?)|NaN|[+-]?Inf)")

_FB_PRINTED = [False]


def _fallback_markers():
    """Print the FALLBACK_TRIGGERED / FALLBACK_JUSTIFIED pair exactly once."""
    if _FB_PRINTED[0]:
        return
    _FB_PRINTED[0] = True
    print("FALLBACK_TRIGGERED: metrics content-type header legs (bare, Accept: application/json, Accept: text/html, Accept: */* on GET /metrics) run via a requests face because the runtime wrapper scripts/runtime/_common.req returns only (status, raw_text) and drops response headers, while this chunk's assertion qdrant_behavioral_metrics_001 explicitly pins the 'content-type text/plain' response header")
    print("[FALLBACK_JUSTIFIED: header capture is unreachable through rt.request — its transport layer scripts/runtime/_common.py req() discards the requests.Response object and returns (r.status_code, r.text) only, so the header half of the documented promise ('HTTP 200 with text/plain Prometheus metrics body', source_url https://api.qdrant.tech/v-1-18-x/api-reference/service/metrics) cannot be observed on the runtime face; the fallback URL is rt.PATHS['metrics'] cross-checked verbatim against raw_knowledge api_endpoints[metrics].url ('/metrics'), and the runtime face still performs the baseline liveness/format probe first — same FALLBACK precedent as R24 boundary_locks_get_003 / R25 boundary_locks_set_003 in this session]")


def safe_request(method, path_key, body=None, path_params=None,
                query_params=None, timeout=30):
    """All non-header HTTP through the runtime; timeout/path_params/body/
    query_params forwarded exactly; path_key from rt.PATHS only."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def metrics_http_raw(accept=None, timeout=15):
    """Declared fallback face: header capture for the content-type legs.
    Returns (status, content_type_header, raw_text)."""
    _fallback_markers()
    headers = {}
    _a = os.environ.get("TESTVDB_AUTH_HEADER", "")
    if _a:
        headers["Authorization"] = _a
    if accept:
        headers["Accept"] = accept
    try:
        r = requests.request("GET", BASE_URL + METRICS_URL,
                             headers=headers, timeout=timeout)
        return r.status_code, (r.headers.get("Content-Type") or ""), r.text
    except Exception as e:
        return 0, "", str(e)


def prometheus_shape(body):
    """Plain-text Prometheus exposition parse (v0.0.4 subset).
    Returns (help_lines, type_lines, sample_lines)."""
    if not body or not body.strip():
        return 0, 0, 0
    help_n = type_n = sample_n = 0
    for line in str(body).splitlines():
        t = line.strip()
        if not t:
            continue
        if t.startswith("#"):
            if t.startswith("# HELP"):
                help_n += 1
            elif t.startswith("# TYPE"):
                type_n += 1
        elif _SAMPLE_RE.match(t):
            sample_n += 1
    return help_n, type_n, sample_n


def parse_maybe_json(raw):
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return b if isinstance(b, (dict, list)) else None


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    print(f"[boundary_metrics_002] run_token={TS} base={BASE_URL}")
    DEFECTS = []
    NOTES = []

    def alive():
        hs, hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        return hs == 200

    def classify_env(s, detail):
        """Shared environment branches. Returns ENV / ABSENT / None."""
        if s == 0 and not alive():
            return "ENV"
        if s in (401, 403):
            NOTES.append(f"{detail}: auth-gated ({s}) — api-key configured "
                         f"and TESTVDB_AUTH_HEADER not accepted; the "
                         f"content-type promise is not adjudicable without "
                         f"credentials")
            return "ENV_AUTH"
        return None

    def header_leg(tag, accept):
        """One header-capture leg: expect 200 + Content-Type text/plain* +
        Prometheus-parseable body. Returns ENV/ENV_AUTH/ABSENT/OK."""
        s, ct, body = metrics_http_raw(accept=accept)
        print(f"[{tag}] status={s} content-type={ct!r} "
              f"bytes={len(str(body))} head={str(body)[:160]!r}")
        if s == 0:
            if not alive():
                return "ENV"
            DEFECTS.append(f"[{tag}] transport failure with /healthz alive — "
                           f"Type3_RuntimeFailure — exc={str(body)[:150]}")
            return "OK"
        if s in (401, 403):
            return classify_env(s, tag) or "OK"
        if 500 <= s <= 599:
            if alive():
                DEFECTS.append(f"[{tag}] answered {s} (5xx crash-class) with "
                               f"/healthz alive — Type3_RuntimeFailure — "
                               f"raw={str(body)[:200]}")
            else:
                return "ENV"
            return "OK"
        if not (200 <= s <= 299):
            if s == 404:
                return "ABSENT"
            DEFECTS.append(f"[{tag}] answered {s} (non-2xx) on the live "
                           f"metrics face — assertion promises HTTP 200 — "
                           f"Type4_StateLogicViolation — raw={str(body)[:200]}")
            return "OK"
        h, t, n = prometheus_shape(body)
        print(f"[{tag}] prometheus shape: HELP={h} TYPE={t} samples={n}")
        if not ct.lower().startswith("text/plain"):
            DEFECTS.append(f"[{tag}] answered 200 but Content-Type is "
                           f"{ct!r}, not text/plain* — the assertion's "
                           f"explicit '(content-type text/plain)' promise is "
                           f"broken on this face — "
                           f"Type4_StateLogicViolation")
        if h + t < 1 or n < 1:
            kind = ("body is JSON, not Prometheus text"
                    if parse_maybe_json(body) is not None
                    else "body is not parseable Prometheus exposition")
            DEFECTS.append(f"[{tag}] answered 200 but {kind} — HELP/TYPE="
                           f"{h + t} samples={n} — format promise broken — "
                           f"Type4_StateLogicViolation — "
                           f"raw={str(body)[:200]}")
        if accept == "application/json" and parse_maybe_json(body) is not None:
            DEFECTS.append(f"[{tag}] Accept: application/json switched the "
                           f"response to a JSON body — the text/plain "
                           f"Prometheus promise is unconditional and must "
                           f"not be content-negotiated away — "
                           f"Type4_StateLogicViolation")
        return "OK"

    try:
        # ---- runtime-face baseline (liveness + format, no headers) ----
        s0, raw0 = safe_request("GET", METRICS_KEY, timeout=20)
        print(f"[baseline runtime GET /metrics] status={s0} "
              f"bytes={len(str(raw0 or ''))} head={str(raw0)[:160]!r}")
        if s0 == 0 or 500 <= s0 <= 599 or s0 in (401, 403):
            env = classify_env(s0, "baseline")
            if env == "ENV":
                for n in NOTES:
                    print(f"NOTE: {n}")
                return "SCRIPT_ERROR"
            if env == "ENV_AUTH":
                for n in NOTES:
                    print(f"NOTE: {n}")
                return "SCRIPT_ERROR"
            if s0 == 0 or 500 <= s0 <= 599:
                # transport/5xx with healthz alive = Type3 (claim), else ENV
                if alive():
                    DEFECTS.append(f"[baseline] answered {s0} with /healthz "
                                   f"alive — Type3_RuntimeFailure — "
                                   f"raw={str(raw0)[:200]}")
                else:
                    return "SCRIPT_ERROR"
        elif s0 == 404:
            ok = alive()
            print(f"[ENDPOINT_ABSENT-check] /metrics answered concrete 404 "
                  f"while /healthz={'200' if ok else 'non-200'} — "
                  f"contradicts the v1.18.0 service_api.rs route-table "
                  f"reading (round reflection); evidence printed, assertion "
                  f"not actuable")
            if ok:
                return "NO_DEFECT"
            return "SCRIPT_ERROR"
        else:
            h, t, n = prometheus_shape(raw0)
            print(f"[baseline] prometheus shape: HELP={h} TYPE={t} "
                  f"samples={n}")
            if h + t < 1 or n < 1:
                DEFECTS.append(f"[baseline] runtime face answered 200 but "
                               f"body does not parse as Prometheus text — "
                               f"Type4_StateLogicViolation — "
                               f"raw={str(raw0)[:200]}")

        # ---- header-capture legs (declared fallback face) ----
        for tag, accept in [
            ("H1 bare", None),
            ("H2 Accept application/json", "application/json"),
            ("H3 Accept text/html", "text/html"),
            ("H4 Accept */*", "*/*"),
        ]:
            rc = header_leg(tag, accept)
            if rc in ("ENV", "ENV_AUTH"):
                for n in NOTES:
                    print(f"NOTE: {n}")
                return "SCRIPT_ERROR"
            if rc == "ABSENT":
                ok = alive()
                print(f"[ENDPOINT_ABSENT-check] fallback leg {tag} answered "
                      f"404 while /healthz={'200' if ok else 'non-200'}")
                if ok:
                    return "NO_DEFECT"
                return "SCRIPT_ERROR"

        for n in NOTES:
            print(f"NOTE: {n}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("metrics content-type identity: every 200 leg carried a "
              "text/plain Content-Type and a parseable Prometheus body, and "
              "Accept-negotiation could not switch the documented format — "
              "NO_DEFECT")
        return "NO_DEFECT"
    finally:
        # read-only face — nothing to tear down; trailing probe is
        # informational only and never flips the verdict (cleanup discipline)
        try:
            hs, _ = safe_request("GET", "healthz", timeout=10)
            print(f"[cleanup probe healthz] status={hs}")
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
