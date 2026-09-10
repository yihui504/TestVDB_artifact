#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_metrics_005
# strategy: malformed_input
# endpoint: metrics
# constraint_ids: qdrant_behavioral_metrics_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/service/metrics
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-07-adjacent parser trust on a telemetry route + G9 method
#   disposition — /metrics is the one route every scraper hits with plain
#   GETs, so non-GET methods with unexpected bodies and malformed query
#   streams (invalid %-escapes, NUL, duplicates, overlong values, junk
#   pairs) are the cheapest inputs able to panic an under-validated
#   handler and falsify "HTTP 200 with text/plain Prometheus metrics
#   body" for the plain-GET reader that follows.
"""
TestVDB Boundary Attack Script — Target: qdrant v1.18.0
Attack: method-face disposition + malformed query-stream robustness x
  qdrant_behavioral_metrics_001 (chunk_metrics scope = metrics GET
  /metrics; the chunk's only unit). Two negative constructions against
  the read-only face (G5: crash-class is the defect; clean 4xx and
  permissive 2xx are both legal): (1) method volley — HEAD / OPTIONS /
  POST (empty + JSON body) / PUT / PATCH / DELETE on a GET-documented
  route; the v-1-18-x shard declares GET-only, so any non-5xx answer is
  an acceptable disposition (404/405 typical for unregistered method
  routes) and a 2xx on a non-GET method is recorded as a G9
  interface-parity NOTE, not a claim (no contract backs a required
  disposition — house precedent state_livez_002); (2) malformed query
  streams forwarded as RAW query strings through the runtime wrapper
  (requests appends string params verbatim, so the wire form survives;
  one caveat printed: requests requote may normalize an invalid escape
  like %ZZ into a literal-% value, in which case the leg still measures
  a junk string for a documented boolean param): invalid %-escape, NUL
  byte %00, empty value, duplicate parameter, 64 KiB overlong value
  (unique-prefixed), junk pairs '&&&=', and an unknown junk parameter.
  Overlong/request-line-limit legs may legitimately DROP the connection
  (414-class enforcement) — a single transport loss is counted, and only
  repeated losses (>=2) with /healthz alive escalate to a Type3 claim
  (race discipline from the session's standing lessons); the face-health
  re-probe distinguishes size-limit enforcement (face still 200) from a
  parser crash (face degraded). Positive brackets (G4): baseline bare
  GET + post-matrix bare GET + post-volley bare GET must all answer 200
  with parseable Prometheus text — if hostile input leaves the face
  degraded (non-2xx/5xx/non-Prometheus on the plain GET that the
  assertion actually covers), that is Type3 (face corrupted) / Type4
  (200 promise broken for the documented face).
Oracle: baseline bare GET answers 200 with >=1 HELP/TYPE and >=1 Prometheus sample line; every method-volley probe (HEAD/OPTIONS/POST-empty/POST-JSON/PUT/PATCH/DELETE) and every malformed-query leg (%ZZ escape, %00 NUL, empty value, duplicate param, 64 KiB overlong, '&&&=', unknown junk param) lands OUTSIDE the 5xx band — any 5xx with /healthz alive = DEFECT Type3_RuntimeFailure, >=2 recovered transport losses with /healthz alive = DEFECT Type3 (single loss counted and face-health-checked), 2xx on a non-GET method or a 200-ignored malformed stream = legal (G9 NOTE recorded); post-volley and post-matrix bare GET re-probes must answer 200 + Prometheus text — a degraded plain-GET face (non-2xx = Type4 200-promise broken, 5xx/transport with /healthz alive = Type3, non-Prometheus 200 body = Type4 format promise broken); 401/403 = SCRIPT_ERROR, 404 + healthz 200 = NO_DEFECT endpoint-absence evidence
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

# method volley on the GET-documented route (bodies stay dicts — the
# runtime forwards them via its json channel; body-parser torture is
# another lane, this volley targets the ROUTE's method disposition)
METHOD_LEGS = [
    ("M1 HEAD", "HEAD", None),
    ("M2 OPTIONS", "OPTIONS", None),
    ("M3 POST empty-body", "POST", None),
    ("M4 POST json-body", "POST", {"query": "x", "vector": [0.1, 0.2]}),
    ("M5 PUT", "PUT", {"vectors": {"size": 4, "distance": "Cosine"}}),
    ("M6 PATCH", "PATCH", {"op": "probe", "path": "/metrics"}),
    ("M7 DELETE", "DELETE", None),
]


def safe_request(method, path_key, body=None, path_params=None,
                query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; query_params may be a RAW STRING (requests appends
    str params verbatim — malformed wire forms survive); path_key from
    rt.PATHS only."""
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
    PFX = "mb5_" + TS + "_"          # unique-prefix discipline
    print(f"[boundary_metrics_005] run_token={TS} base={BASE_URL}")
    DEFECTS = []
    NOTES = []
    trans_losses = []   # (tag, raw) — recovered transport losses (status 0)

    # malformed query legs are built here (unique prefix inside the values)
    raw_query_legs = [
        ("Q1 invalid %-escape", "anonymize=%ZZ"),
        ("Q2 NUL byte %00", "anonymize=%00"),
        ("Q3 empty value", "anonymize="),
        ("Q4 duplicate params", "anonymize=true&anonymize=false"),
        ("Q5 overlong 64k value", "anonymize=" + PFX + "a" * 65536),
        ("Q6 junk pairs", "&&&="),
        ("Q7 unknown junk param", PFX + "junk=" + "z" * 1024),
    ]

    def alive():
        hs, hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        return hs == 200

    def baseline_control(tag):
        """Bare GET bracket: must be 200 + Prometheus text.
        Returns ENV/ENV_AUTH/ABSENT/OK."""
        s, raw = safe_request("GET", METRICS_KEY, timeout=15)
        body = str(raw) if raw is not None else ""
        print(f"[{tag}] status={s} bytes={len(body)} head={body[:160]!r}")
        if s == 0:
            if not alive():
                return "ENV"
            DEFECTS.append(f"[{tag}] transport failure with /healthz alive — "
                           f"Type3_RuntimeFailure — exc={body[:150]}")
            return "OK"
        if s in (401, 403):
            NOTES.append(f"[{tag}] auth-gated ({s}) — not adjudicable")
            return "ENV_AUTH"
        if 500 <= s <= 599:
            if alive():
                DEFECTS.append(f"[{tag}] answered {s} (5xx) with /healthz "
                               f"alive — Type3_RuntimeFailure — "
                               f"raw={body[:200]}")
                return "OK"
            return "ENV"
        if s == 404:
            return "ABSENT"
        if not (200 <= s <= 299):
            DEFECTS.append(f"[{tag}] plain-GET face answered {s} — the "
                           f"assertion's 200 promise is broken for the "
                           f"documented face — Type4_StateLogicViolation — "
                           f"raw={body[:200]}")
            return "OK"
        h, t, n = prometheus_shape(body)
        print(f"[{tag}] prometheus shape: HELP={h} TYPE={t} samples={n}")
        if h + t < 1 or n < 1:
            DEFECTS.append(f"[{tag}] plain-GET face answered 200 but body "
                           f"does not parse as Prometheus text — format "
                           f"promise broken — Type4_StateLogicViolation — "
                           f"raw={body[:200]}")
        return "OK"

    def hostile_leg(tag, method, body, raw_query):
        """One hostile probe: method volley or malformed query stream.
        Non-5xx dispositions are legal (G5/G9); transport losses are
        counted; only repeated losses or 5xx escalate to Type3.
        Returns ENV/ENV_AUTH/OK."""
        try:
            if raw_query is not None:
                s, raw = safe_request(method, METRICS_KEY,
                                      query_params=raw_query, timeout=15)
            else:
                s, raw = safe_request(method, METRICS_KEY, body=body,
                                      timeout=15)
        except Exception as e:   # req() never raises; belt-and-braces guard
            s, raw = 0, str(e)
        r = str(raw) if raw is not None else ""
        print(f"[{tag}] status={s} bytes={len(r)} head={r[:160]!r}")
        if s == 0:
            if not alive():
                return "ENV"
            face_hs, face_raw = safe_request("GET", METRICS_KEY, timeout=15)
            fh, ft, fn = prometheus_shape(face_raw)
            face_ok = face_hs == 200 and (fh + ft) >= 1 and fn >= 1
            trans_losses.append((tag, r[:100]))
            NOTES.append(f"[{tag}] transport loss (status 0) — face-health "
                         f"re-probe answered {face_hs} "
                         f"({'healthy Prometheus' if face_ok else 'DEGRADED'}"
                         f") — single losses on a size-limit leg are legal "
                         f"connection enforcement; counted for the "
                         f">=2-reproduction rule")
            if not face_ok:
                DEFECTS.append(f"[{tag}] transport loss AND the plain-GET "
                               f"face is degraded after it (re-probe "
                               f"status={face_hs}) — parser crash on "
                               f"malformed input — Type3_RuntimeFailure — "
                               f"exc={r[:150]}")
            return "OK"
        if s in (401, 403):
            NOTES.append(f"[{tag}] auth-gated ({s}) — not adjudicable")
            return "ENV_AUTH"
        if 500 <= s <= 599:
            if alive():
                DEFECTS.append(f"[{tag}] answered {s} (5xx crash-class) with "
                               f"/healthz alive — the handler crashed on "
                               f"hostile input instead of degrading to 4xx — "
                               f"Type3_RuntimeFailure — raw={r[:200]}")
            else:
                return "ENV"
            return "OK"
        if 200 <= s <= 299:
            if method != "GET":
                NOTES.append(f"G9 DISPOSITION [{tag}]: 2xx on a non-GET "
                             f"method against the GET-documented metrics "
                             f"route — permissive routing recorded, not "
                             f"claimable (no contract backs a required "
                             f"disposition; house precedent "
                             f"state_livez_002)")
            else:
                NOTES.append(f"[{tag}] malformed stream tolerated with 200 — "
                             f"legal graceful degradation (junk ignored)")
        elif 400 <= s <= 499:
            print(f"[{tag}] clean defensive rejection ({s}) — not a defect")
        return "OK"

    try:
        # ---- baseline bracket ----
        rc = baseline_control("K0 baseline bare")
        if rc in ("ENV", "ENV_AUTH"):
            for n in NOTES:
                print(f"NOTE: {n}")
            return "SCRIPT_ERROR"
        if rc == "ABSENT":
            ok = alive()
            print(f"[ENDPOINT_ABSENT-check] /metrics answered 404 while "
                  f"/healthz={'200' if ok else 'non-200'} — contradicts the "
                  f"v1.18.0 service_api.rs route-table reading (round "
                  f"reflection); evidence printed")
            if ok:
                return "NO_DEFECT"
            return "SCRIPT_ERROR"

        # ---- (1) method volley ----
        for tag, method, body in METHOD_LEGS:
            rc = hostile_leg(tag, method, body, None)
            if rc in ("ENV", "ENV_AUTH"):
                for n in NOTES:
                    print(f"NOTE: {n}")
                return "SCRIPT_ERROR"

        # ---- interlude: plain-GET face must survive the volley ----
        rc = baseline_control("K1 post-volley bare")
        if rc in ("ENV", "ENV_AUTH"):
            for n in NOTES:
                print(f"NOTE: {n}")
            return "SCRIPT_ERROR"
        if rc == "ABSENT":
            ok = alive()
            print(f"[ENDPOINT_ABSENT-check] /metrics answered 404 after the "
                  f"method volley while "
                  f"/healthz={'200' if ok else 'non-200'} — volley removed "
                  f"the face; evidence printed")
            if ok:
                DEFECTS.append("[K1 post-volley bare] the method volley left "
                               "the metrics route answering 404 while the "
                               "process is alive — face corrupted — "
                               "Type3_RuntimeFailure")
            else:
                return "SCRIPT_ERROR"

        # ---- (2) malformed query streams (raw string wire forms) ----
        for tag, rawq in raw_query_legs:
            rc = hostile_leg(tag, "GET", None, rawq)
            if rc in ("ENV", "ENV_AUTH"):
                for n in NOTES:
                    print(f"NOTE: {n}")
                return "SCRIPT_ERROR"

        # ---- closing bracket: face must still keep the promise ----
        rc = baseline_control("K2 post-matrix bare")
        if rc in ("ENV", "ENV_AUTH"):
            for n in NOTES:
                print(f"NOTE: {n}")
            return "SCRIPT_ERROR"
        if rc == "ABSENT":
            ok = alive()
            print(f"[ENDPOINT_ABSENT-check] /metrics answered 404 after the "
                  f"full matrix while "
                  f"/healthz={'200' if ok else 'non-200'}")
            if ok:
                DEFECTS.append("[K2 post-matrix bare] the hostile matrix left "
                               "the metrics route answering 404 while the "
                               "process is alive — face corrupted — "
                               "Type3_RuntimeFailure")
            else:
                return "SCRIPT_ERROR"

        if len(trans_losses) >= 2:
            DEFECTS.append(f"{len(trans_losses)} transport losses on the "
                           f"metrics route, each with /healthz alive "
                           f"({[t for (t, _) in trans_losses]}) — repeated "
                           f"connection instability on hostile input — "
                           f"Type3_RuntimeFailure")

        for n in NOTES:
            print(f"NOTE: {n}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("metrics method-face + malformed-query robustness: every "
              "hostile probe landed outside the 5xx band (dispositions "
              "recorded as G9 notes), single transport losses were "
              "size-limit enforcement with a healthy face re-probe, and "
              "the plain-GET 200/Prometheus promise held across all three "
              "brackets — NO_DEFECT")
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
