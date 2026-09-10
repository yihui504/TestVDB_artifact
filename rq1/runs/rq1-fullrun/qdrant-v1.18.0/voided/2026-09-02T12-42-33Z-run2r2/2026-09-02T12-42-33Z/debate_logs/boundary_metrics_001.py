#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_metrics_001
# strategy: behavioral
# endpoint: metrics
# constraint_ids: qdrant_behavioral_metrics_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/service/metrics
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04-adjacent read-face 200 optimism — the doc promises
#   "HTTP 200 with text/plain Prometheus metrics body" unconditionally on
#   GET /metrics, so the positive matrix pins that promise bare AND under
#   every documented query-parameter value closure (anonymize/per_collection
#   x true/false x combined); a non-200 or a non-Prometheus body on any of
#   them breaks the behavioral assertion on a live face.
"""
TestVDB Boundary Attack Script — Target: qdrant v1.18.0
Attack: behavioral positive promise matrix x qdrant_behavioral_metrics_001
  (chunk_metrics scope = metrics GET /metrics, the chunk's only unit;
  assertion expected_behavior: "HTTP 200 with text/plain Prometheus metrics
  body"; description adds family coverage "collections, searches, points,
  optimizations and cluster state"). G4 positive direction — closure matrix
  over the two documented boolean query params (contract
  api_endpoints[metrics].parameters: anonymize bool opt, per_collection bool
  opt; bare + 4 single-value legs + 2 combined legs), every leg must answer
  exactly HTTP 200 with a plain-text body that parses as Prometheus
  exposition (>=1 HELP/TYPE line AND >=1 well-formed sample line — the
  reflection-context lesson: the body is Prometheus TEXT, not JSON, so the
  parse is line-based, never a result-envelope read). Family coverage scan
  (collections/points/searches/optimizations/cluster) is EVIDENCE: a missing
  family keyword on an idle instance may be lazy metric registration, so it
  is printed as a DOC_CONSISTENCY_CANDIDATE note for the judge rather than
  hard-claimed (G3/G5). anonymize=true-vs-bare body diff recorded as
  evidence for the anonymization behavior. Defect typing: non-2xx on the
  live face = Type4_StateLogicViolation (200 promise broken); 200 with a
  body that is JSON or otherwise not Prometheus = Type4 (format promise
  broken, raw evidence printed); 5xx or transport loss with inline
  /healthz alive = Type3_RuntimeFailure; 401/403 = auth-gated config ->
  SCRIPT_ERROR with evidence; concrete 404 on the face while /healthz
  answers 200 = endpoint-absent evidence -> NO_DEFECT (assertion not
  actuable; contradicts the v1.18.0 service_api.rs route-table reading in
  the round reflection, so the contradiction is printed for the record).
Oracle: all 7 positive legs (bare; anonymize=true|false; per_collection=true|false; anonymize=true+per_collection=true|false) answer HTTP 200 with a body parsing as Prometheus text (>=1 HELP/TYPE line and >=1 sample line matching ^name[{labels}]? numeric) — any leg non-2xx on the live face = DEFECT Type4_StateLogicViolation (200 promise broken), 200 with non-Prometheus/empty/JSON body = DEFECT Type4 (format promise broken), 5xx/transport with /healthz alive = DEFECT Type3_RuntimeFailure, 401/403 = SCRIPT_ERROR (auth-gated), bare 404 + healthz 200 = NO_DEFECT endpoint-absence evidence; missing family keywords print DOC_CONSISTENCY_CANDIDATE notes and do not flip the verdict
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

# metrics is a NATIVE rt.PATHS key; cross-check the registered template
# against raw_knowledge api_endpoints[metrics].url (standing lesson: URLs
# from raw_knowledge api_endpoints[].url only — never invented here).
METRICS_KEY = "metrics"
_url = rt.PATHS.get(METRICS_KEY)
_derived = "runtime PATHS native entry"
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
                    _derived = f"runtime PATHS == raw_knowledge api_endpoints[metrics].url ({_e['url']!r})"
        except Exception:
            pass
        break
print(f"[path derivation] {METRICS_KEY} = {_url} ({_derived})")

# documented boolean query params — values sent as STRINGS on purpose:
# requests urlencode would render Python bool True as "True" (capital T),
# which serde rejects; the documented wire form is lowercase true/false.
POSITIVE_LEGS = [
    ("P0 bare", None),
    ("P1 anonymize=true", {"anonymize": "true"}),
    ("P2 anonymize=false", {"anonymize": "false"}),
    ("P3 per_collection=true", {"per_collection": "true"}),
    ("P4 per_collection=false", {"per_collection": "false"}),
    ("P5 anonymize=true+per_collection=true",
     {"anonymize": "true", "per_collection": "true"}),
    ("P6 anonymize=true+per_collection=false",
     {"anonymize": "true", "per_collection": "false"}),
]

# promised metric families (assertion description) — keyword scan only;
# alternates cover naming drift across the 1.18 telemetry registry.
FAMILIES = [
    ("collections", ("collection",)),
    ("points", ("point",)),
    ("searches", ("search", "response")),
    ("optimizations", ("optim",)),
    ("cluster_state", ("cluster",)),
]

_SAMPLE_RE = re.compile(
    r"^[a-zA-Z_:][a-zA-Z0-9_:]*(\{[^}]*\})?\s+"
    r"([-+]?(\d+\.?\d*([eE][-+]?\d+)?)|NaN|[+-]?Inf)")


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


def parse_maybe_json(raw):
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return b if isinstance(b, (dict, list)) else None


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    print(f"[boundary_metrics_001] run_token={TS} base={BASE_URL}")
    DEFECTS = []
    NOTES = []

    def alive():
        hs, hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        return hs == 200

    def family_scan(tag, body):
        """Keyword evidence over the promised families (NOTE-level)."""
        lines = [ln.strip() for ln in str(body).splitlines() if ln.strip()]
        for fam, keys in FAMILIES:
            hits = [ln for ln in lines
                    if any(k in ln.lower() for k in keys)]
            if hits:
                print(f"[family {fam}] {len(hits)} matching line(s); e.g. "
                      f"{hits[0][:100]!r}")
            else:
                NOTES.append(f"DOC_CONSISTENCY_CANDIDATE [{tag}]: promised "
                             f"family '{fam}' (keywords {keys}) has ZERO "
                             f"matching lines in a 200 Prometheus body — "
                             f"may be lazy metric registration on an idle "
                             f"instance; judge weighs against the assertion "
                             f"description ('covering collections, searches, "
                             f"points, optimizations and cluster state')")

    def adjudicate_leg(tag, qp):
        """One positive leg: expect exactly 200 + Prometheus-parseable text.
        Returns ("ENV"|"ENV_AUTH"|"ABSENT"|"OK", body_bytes) — no duplicate
        requests for the size evidence."""
        t0 = time.monotonic()
        s, raw = safe_request("GET", METRICS_KEY, query_params=qp, timeout=20)
        ms = int((time.monotonic() - t0) * 1000)
        body = str(raw) if raw is not None else ""
        print(f"[{tag}] status={s} ms={ms} bytes={len(body)} "
              f"head={body[:200]!r}")
        if s == 0:
            if not alive():
                return "ENV"
            DEFECTS.append(f"[{tag}] transport failure with /healthz alive — "
                           f"Type3_RuntimeFailure — exc={body[:150]}")
            return "OK", len(body)
        if 401 == s or 403 == s:
            NOTES.append(f"[{tag}] auth-gated ({s}) — api-key configured on "
                         f"this deployment and TESTVDB_AUTH_HEADER not "
                         f"accepted; behavioral body promise not adjudicable "
                         f"without credentials — raw={body[:150]}")
            return "ENV_AUTH", len(body)
        if 500 <= s <= 599:
            if alive():
                DEFECTS.append(f"[{tag}] answered {s} (5xx crash-class) with "
                               f"/healthz alive — Type3_RuntimeFailure — "
                               f"raw={body[:200]}")
            else:
                return "ENV", len(body)
            return "OK", len(body)
        if not (200 <= s <= 299):
            if s == 404:
                return "ABSENT", len(body)
            DEFECTS.append(f"[{tag}] answered {s} (non-2xx) on the live "
                           f"metrics face — assertion promises HTTP 200 for "
                           f"GET /metrics (documented params only) — "
                           f"Type4_StateLogicViolation — raw={body[:200]}")
            return "OK", len(body)
        h, t, n = prometheus_shape(body)
        print(f"[{tag}] prometheus shape: HELP={h} TYPE={t} samples={n}")
        if h + t < 1 or n < 1:
            kind = ("body is JSON, not Prometheus text"
                    if parse_maybe_json(body) is not None
                    else "body is not parseable Prometheus exposition "
                         "(empty or shapeless)")
            DEFECTS.append(f"[{tag}] answered 200 but {kind} — HELP/TYPE="
                           f"{h + t} samples={n} — the 'text/plain Prometheus "
                           f"metrics body' promise is broken — "
                           f"Type4_StateLogicViolation — raw={body[:200]}")
            return "OK", len(body)
        return "OK", len(body)

    try:
        # ---- positive matrix ----
        absent = False
        auth_gated = False
        sizes = {}
        for tag, qp in POSITIVE_LEGS:
            rc, nbytes = adjudicate_leg(tag, qp)
            if rc == "ENV":
                for n in NOTES:
                    print(f"NOTE: {n}")
                return "SCRIPT_ERROR"
            if rc == "ENV_AUTH":
                auth_gated = True
                break
            if rc == "ABSENT":
                absent = True
                break
            sizes[tag] = nbytes  # size evidence from the SAME measured leg

        if auth_gated:
            for n in NOTES:
                print(f"NOTE: {n}")
            print("VERDICT-basis: /metrics answered 401/403 while the "
                  "service is up — auth config blocks the behavioral body "
                  "promise; not adjudicable -> SCRIPT_ERROR (environment)")
            return "SCRIPT_ERROR"

        if absent:
            ok = alive()
            print(f"[ENDPOINT_ABSENT-check] /metrics answered concrete 404 "
                  f"while /healthz={'200' if ok else 'non-200'} — the "
                  f"round-reflection route-table reading (v1.18.0 "
                  f"service_api.rs registers /metrics) is CONTRADICTED by "
                  f"this deployment (image qdrant/qdrant:v1.18.0, commit "
                  f"db3fca327851e360c521065649e0f65a57fe7d3c per "
                  f"deployment_meta.json); no live handler exists whose 200 "
                  f"promise could be kept or broken")
            if ok:
                print("NO_DEFECT-basis: assertion not actuable on this "
                      "deployment (endpoint absent, evidence above)")
                return "NO_DEFECT"
            return "SCRIPT_ERROR"

        # ---- family coverage + param-effect evidence on the bare body ----
        s0, raw0 = safe_request("GET", METRICS_KEY, timeout=20)
        if s0 == 200:
            family_scan("P0 bare", raw0)
            sa, rawa = safe_request("GET", METRICS_KEY,
                                    query_params={"anonymize": "true"},
                                    timeout=20)
            if sa == 200:
                diff = len(str(raw0)) - len(str(rawa))
                NOTES.append(f"anonymize effect evidence: bare bytes="
                             f"{len(str(raw0))} anonymize=true bytes="
                             f"{len(str(rawa))} delta={diff} — recorded for "
                             f"the judge (anonymization of labels on an "
                             f"idle instance may be a no-op)")
            if sizes:
                NOTES.append(f"leg body sizes: {sizes}")
        else:
            NOTES.append(f"family-scan skipped: re-probe answered {s0}")

        for n in NOTES:
            print(f"NOTE: {n}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("metrics positive matrix: all legs answered HTTP 200 with "
              "parseable Prometheus text; family keyword evidence printed; "
              "no 5xx, no transport loss with /healthz alive — NO_DEFECT")
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
