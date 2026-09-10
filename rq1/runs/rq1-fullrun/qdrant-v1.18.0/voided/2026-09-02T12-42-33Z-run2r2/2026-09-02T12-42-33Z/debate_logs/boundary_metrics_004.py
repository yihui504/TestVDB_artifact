#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_metrics_004
# strategy: boundary
# endpoint: metrics
# constraint_ids: qdrant_behavioral_metrics_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/service/metrics
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 Boundary Default Optimism — the documented timeout
#   query param is an integer; the optimism is that any integer parses and
#   the gather path stays bounded. Negative/overflow integers are the
#   classic unbounded-wait hazard (a negative i64 reinterpreted as u64
#   milliseconds is a ~585-year duration), so this matrix probes the
#   integer boundary lattice with a bounded client clock as the oracle.
"""
TestVDB Boundary Attack Script — Target: qdrant v1.18.0
Attack: numeric boundary matrix on the documented integer query param
  timeout x qdrant_behavioral_metrics_001 (chunk_metrics scope = metrics
  GET /metrics; the chunk's only unit; the assertion's "HTTP 200 with
  text/plain Prometheus metrics body" promise must hold for every legal
  integer and survive every boundary/overflow integer). Strategy-1/
  strategy-6 hybrid on the single declared numeric param (contract
  api_endpoints[metrics].parameters: timeout integer optional; OpenAPI
  provenance "mechanical backfill" — see adjudication caveat below).
  G4 positive controls: bare + timeout=1 (a plainly legal positive
  integer) must answer 200 fast with Prometheus text. Boundary lattice:
  0 (min-closure), -1 / -100 (negative — Duration::from_millis(negative
  as u64) wrap hazard), 2147483647 (i32 max), 2147483648 (i32 max + 1),
  9223372036854775807 (i64 max), 9223372036854775808 (i64 max + 1, out
  of i64 range — serde u64/i64 boundary). Typed oracles (G5): a clean
  400/422 = explicit rejection, not a defect; a 200 answering within the
  bounded client clock (10 s) = value ignored/clamped, legal (the
  promise is "no crash, no unbounded wait", NOT "must reject" — strategy
  6 discipline); a client-clock expiry (transport timeout) with an
  immediate /healthz 200 = Type3_RuntimeFailure hang-class (the endpoint
  accepted an integer that made the handler wait unboundedly while the
  process is demonstrably alive — D3b rule 3: liveness re-check on the
  lightweight health route, never inferred from a business endpoint);
  5xx with /healthz alive = Type3 crash-class; a 200 that takes >= 8 s
  (slow but completed) is recorded as a near-hang NOTE for the judge,
  not a claim. Post-matrix control re-pins the 200/Prometheus promise.
Oracle: bare and timeout=1 controls answer 200 in <2 s with >=1 HELP/TYPE and >=1 Prometheus sample; each boundary leg (timeout=0|-1|-100|2147483647|2147483648|9223372036854775807|9223372036854775808) answers either 400/422 (clean reject, NO_DEFECT leg) or 200 within the 10 s client clock (ignored/clamped, NO_DEFECT leg) — a leg whose 10 s client clock expires followed by an immediate /healthz 200 = DEFECT Type3_RuntimeFailure (hang-class: unbounded server-side wait on a documented integer param), any 5xx with /healthz alive = DEFECT Type3, 200 taking >= 8 s = near-hang NOTE (not claimed), post-matrix bare control must still answer 200 + Prometheus text (degraded face = Type3), 401/403 = SCRIPT_ERROR (auth-gated), 404 + healthz 200 = NO_DEFECT endpoint-absence evidence
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

# metrics is a NATIVE rt.PATHS key; cross-check against raw_knowledge
# api_endpoints[metrics].url (standing lesson: URLs from raw_knowledge
# api_endpoints[].url only — never invented here).
METRICS_KEY = "metrics"
_url = rt.PATHS.get(METRICS_KEY)
for _p in Path(__file__).resolve().parents:
    _rk = _p / "raw_knowledge.json"
    if _rk.exists():
        try:
            _rkd = json.loads(_rk.read_text(encoding="utf-8"))
            for _e in _rkd.get("api_endpoints", []):
                if _e.get("path") == "metrics" and _e.get("url"):
                    if _url != _e["url"]:
                        print(f"VERDICT: SCRIPT_ERROR - rt.PATHS[{METRICS_KEY}]={_url!r} "
                              f"!= raw_knowledge url {_e['url']!r}")
                        sys.exit(2)
        except Exception:
            pass
        break
print(f"[path derivation] {METRICS_KEY} = {_url} (rt.PATHS == raw_knowledge "
      f"api_endpoints[metrics].url)")

_SAMPLE_RE = re.compile(
    r"^[a-zA-Z_:][a-zA-Z0-9_:]*(\{[^}]*\})?\s+"
    r"([-+]?(\d+\.?\d*([eE][-+]?\d+)?)|NaN|[+-]?Inf)")

LEG_TIMEOUT_S = 10        # bounded client clock per boundary leg
NEAR_HANG_MS = 8000       # completed-but-slow evidence threshold
BOUNDARY_LEGS = [
    "0",
    "-1",
    "-100",
    "2147483647",          # i32 max
    "2147483648",          # i32 max + 1
    "9223372036854775807",  # i64 max
    "9223372036854775808",  # i64 max + 1 (u64 territory)
]


def safe_request(method, path_key, body=None, path_params=None,
                query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; path_key from rt.PATHS only ("metrics" -> /metrics)."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


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


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    print(f"[boundary_metrics_004] run_token={TS} base={BASE_URL} "
          f"client_clock={LEG_TIMEOUT_S}s")
    DEFECTS = []
    NOTES = []

    def alive():
        hs, hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        return hs == 200

    def run_leg(tag, qp, timeout_s):
        """One measured leg with elapsed clock.
        Returns (status, body, elapsed_ms)."""
        t0 = time.monotonic()
        s, raw = safe_request("GET", METRICS_KEY, query_params=qp,
                              timeout=timeout_s)
        ms = int((time.monotonic() - t0) * 1000)
        body = str(raw) if raw is not None else ""
        print(f"[{tag}] status={s} ms={ms} bytes={len(body)} "
              f"head={body[:160]!r}")
        return s, body, ms

    def adjudicate(tag, s, body, ms, hang_claimable):
        """Typed adjudication for boundary legs. hang_claimable=True means
        a client-clock expiry is a hang-class Type3 claim. Returns
        ENV/ENV_AUTH/ABSENT/None."""
        if s == 0:
            if not alive():
                return "ENV"
            low = body.lower()
            looks_timeout = ("timed out" in low or "timeout" in low
                             or "readtimeout" in low.replace(" ", ""))
            if looks_timeout and hang_claimable:
                DEFECTS.append(f"[{tag}] the bounded client clock "
                               f"({LEG_TIMEOUT_S}s) EXPIRED while /healthz "
                               f"answered 200 immediately after — the "
                               f"handler accepted this documented integer "
                               f"value and then waited unboundedly — "
                               f"Type3_RuntimeFailure (hang-class) — "
                               f"exc={body[:150]}")
            else:
                DEFECTS.append(f"[{tag}] transport failure with /healthz "
                               f"alive — Type3_RuntimeFailure — "
                               f"exc={body[:150]}")
            return None
        if s in (401, 403):
            NOTES.append(f"[{tag}] auth-gated ({s}) — not adjudicable "
                         f"without credentials")
            return "ENV_AUTH"
        if 500 <= s <= 599:
            if alive():
                DEFECTS.append(f"[{tag}] answered {s} (5xx crash-class) with "
                               f"/healthz alive — Type3_RuntimeFailure — "
                               f"raw={body[:200]}")
                return None
            return "ENV"
        if s == 404:
            return "ABSENT"
        return None

    def handle_env(env):
        if env in ("ENV", "ENV_AUTH"):
            for n in NOTES:
                print(f"NOTE: {n}")
            return "SCRIPT_ERROR"
        return None

    try:
        # ---- positive controls ----
        for tag, qp in [("C0 bare", None),
                        ("C1 timeout=1 (legal positive int)",
                         {"timeout": "1"})]:
            s, body, ms = run_leg(tag, qp, LEG_TIMEOUT_S)
            env = adjudicate(tag, s, body, ms, hang_claimable=False)
            if env:
                rc = handle_env(env)
                if rc:
                    return rc
            if s == 404:
                ok = alive()
                print(f"[ENDPOINT_ABSENT-check] /metrics answered 404 while "
                      f"/healthz={'200' if ok else 'non-200'} — contradicts "
                      f"the v1.18.0 route-table reading; evidence printed")
                if ok:
                    return "NO_DEFECT"
                return "SCRIPT_ERROR"
            if 200 <= s <= 299:
                h, t, n = prometheus_shape(body)
                print(f"[{tag}] prometheus shape: HELP={h} TYPE={t} "
                      f"samples={n}")
                if h + t < 1 or n < 1:
                    DEFECTS.append(f"[{tag}] control answered 200 but body "
                                   f"does not parse as Prometheus text — "
                                   f"Type4_StateLogicViolation — "
                                   f"raw={body[:200]}")
                if ms >= 2000:
                    NOTES.append(f"[{tag}] control took {ms} ms — slower "
                                 f"than a 1 s-gather budget suggests; "
                                 f"recorded for the judge")
            else:
                DEFECTS.append(f"[{tag}] control answered {s} (non-2xx) on "
                               f"the live metrics face — "
                               f"Type4_StateLogicViolation — "
                               f"raw={body[:200]}")

        # ---- boundary lattice on timeout ----
        for val in BOUNDARY_LEGS:
            tag = f"B timeout={val}"
            s, body, ms = run_leg(tag, {"timeout": val}, LEG_TIMEOUT_S)
            env = adjudicate(tag, s, body, ms, hang_claimable=True)
            if env:
                rc = handle_env(env)
                if rc:
                    return rc
                if env == "ABSENT":
                    ok = alive()
                    print(f"[ENDPOINT_ABSENT-check] /metrics answered 404 "
                          f"while /healthz={'200' if ok else 'non-200'}")
                    if ok:
                        return "NO_DEFECT"
                    return "SCRIPT_ERROR"
            if 400 <= s <= 422 and s != 404:
                print(f"[{tag}] clean rejection ({s}) — boundary integer "
                      f"explicitly refused — not a defect")
            elif 200 <= s <= 299:
                h, t, n = prometheus_shape(body)
                shape_ok = h + t >= 1 and n >= 1
                print(f"[{tag}] accepted in {ms} ms (prometheus shape ok="
                      f"{shape_ok}) — value ignored/clamped, legal under the "
                      f"no-crash/no-hang oracle")
                if not shape_ok:
                    DEFECTS.append(f"[{tag}] answered 200 in {ms} ms but "
                                   f"body does not parse as Prometheus text "
                                   f"— Type4_StateLogicViolation — "
                                   f"raw={body[:200]}")
                if ms >= NEAR_HANG_MS:
                    NOTES.append(f"NEAR-HANG EVIDENCE [{tag}]: 200 but took "
                                 f"{ms} ms (threshold {NEAR_HANG_MS} ms) — "
                                 f"the integer seems to reach a wait path; "
                                 f"recorded for the judge (not claimed: "
                                 f"completed within the client clock)")
            elif s != 0 and s != 404 and not (500 <= s <= 599):
                NOTES.append(f"[{tag}] unexpected status {s} — recorded for "
                             f"the judge — raw={body[:150]}")

        # ---- post-matrix control ----
        s, body, ms = run_leg("post-matrix bare", None, LEG_TIMEOUT_S)
        env = adjudicate("post-matrix bare", s, body, ms,
                         hang_claimable=False)
        if env:
            rc = handle_env(env)
            if rc:
                return rc
            if env == "ABSENT":
                NOTES.append("[post-matrix bare] face answered 404 after the "
                             "boundary matrix — face removed mid-run; "
                             "recorded")
        if 200 <= s <= 299:
            h, t, n = prometheus_shape(body)
            if h + t < 1 or n < 1:
                DEFECTS.append(f"[post-matrix bare] face degraded after the "
                               f"boundary matrix: 200 body no longer parses "
                               f"as Prometheus text — Type3_RuntimeFailure")
        elif 400 <= s <= 499:
            DEFECTS.append(f"[post-matrix bare] answered {s} after the "
                           f"boundary matrix — the face degraded under "
                           f"boundary integers — Type3_RuntimeFailure")

        for n in NOTES:
            print(f"NOTE: {n}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("metrics timeout boundary lattice: every boundary integer was "
              "cleanly rejected or accepted within the bounded client clock "
              "with the 200/Prometheus promise intact, no hang, no 5xx, "
              "face healthy afterwards — NO_DEFECT")
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
