#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_metrics_003
# strategy: type
# endpoint: metrics
# constraint_ids: qdrant_behavioral_metrics_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/service/metrics
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 Parameter Type Coercion Trust — the documented query
#   params anonymize/per_collection are declared boolean and timeout
#   integer (v-1-18-x OpenAPI); the trust assumption is that the REST
#   framework's serde layer rejects non-boolean/non-integer wire values.
#   This script challenges it with the strategy-2 confusion matrix.
"""
TestVDB Boundary Attack Script — Target: qdrant v1.18.0
Attack: type confusion matrix on the documented metrics query params x
  qdrant_behavioral_metrics_001 (chunk_metrics scope = metrics GET
  /metrics; the chunk's only unit). G4 pairing: positive control legs
  (bare + anonymize=true + per_collection=false, all documented wire
  forms, lowercase strings — Python bool True would urlencode as "True"
  and confuse the probe itself) must answer 200 with Prometheus text,
  proving the face live before any confusion leg counts. Negative legs
  (strategy 2, BS-01): non-boolean wire values for the declared-boolean
  params anonymize/per_collection (notaboolean / TRUE / 1 / yes / 2 / 0 /
  maybe / null-string) and non-integer values for the declared-integer
  param timeout (abc / 1.5 / true), plus one position-confusion leg
  (api-key — documented as a string auth param — sent as a query param
  with a junk unique-prefixed value). Parameter placement (spec
  discipline): all three params are query params per the contract
  parameters list — sent via query_params, never stuffed into a body.
  Typed oracles (G5): boolean/integer confusion legs answering 400/422 =
  clean serde rejection (NO_DEFECT leg); 200 = Type1_IllegalSuccess
  candidate — the documented type constraint was not enforced (judge
  weighs the by-design-ignore possibility, mirroring the threat model's
  filter=null note; for timeout the OpenAPI provenance is "mechanical
  backfill", so a 200 there is recorded as a weaker doc-consistency NOTE
  rather than a Type1 claim); 5xx or transport loss with /healthz alive =
  Type3_RuntimeFailure. The api-key position leg is evidence-only
  (non-5xx): 200 = no auth configured (expected on the local container
  per round reflection) or ignored param; 401 = auth configured and
  bogus key correctly rejected — both legal, neither claimable without
  knowing the deployment's auth config.
Oracle: positive controls (bare, anonymize=true, per_collection=false) all answer 200 with >=1 HELP/TYPE and >=1 Prometheus sample line; each of the 8 boolean-confusion legs (anonymize=notaboolean|TRUE|1|yes; per_collection=2|0|maybe|null) answers 400/422 = clean reject (NO_DEFECT leg) — a 200 on any of them = DEFECT Type1_IllegalSuccess (documented boolean type unenforced, flagged for judge by-design adjudication), 5xx/transport with /healthz alive = DEFECT Type3_RuntimeFailure; each timeout-type leg (abc/1.5/true) answering 200 prints a doc-consistency NOTE (mechanical-backfill provenance, not claimed) while 400/422 = clean and 5xx/transport+alive = Type3; api-key-as-query leg is non-claimable evidence (non-5xx legal); positive controls failing non-2xx on the live face = DEFECT Type4 (200 promise broken, 401/403 = SCRIPT_ERROR, 404+healthz200 = NO_DEFECT absence evidence)
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

# documented boolean params: strictly-typed confusion legs (Type1 if 200)
BOOL_CONFUSION_LEGS = [
    ("N1 anonymize=notaboolean", "anonymize", "notaboolean"),
    ("N2 anonymize=TRUE", "anonymize", "TRUE"),
    ("N3 anonymize=1", "anonymize", "1"),
    ("N4 anonymize=yes", "anonymize", "yes"),
    ("N5 per_collection=2", "per_collection", "2"),
    ("N6 per_collection=0", "per_collection", "0"),
    ("N7 per_collection=maybe", "per_collection", "maybe"),
    ("N8 per_collection=null", "per_collection", "null"),
]
# declared-integer param, OpenAPI provenance "mechanical backfill":
# 200 legs recorded as doc-consistency NOTEs, not Type1 claims
INT_CONFUSION_LEGS = [
    ("N9 timeout=abc", "timeout", "abc"),
    ("N10 timeout=1.5", "timeout", "1.5"),
    ("N11 timeout=true", "timeout", "true"),
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
    PFX = "mb3_" + TS + "_"          # unique-prefix discipline
    print(f"[boundary_metrics_003] run_token={TS} base={BASE_URL}")
    DEFECTS = []
    NOTES = []

    def alive():
        hs, hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        return hs == 200

    def leg(tag, qp):
        """One measured GET /metrics leg. Returns (status, body)."""
        s, raw = safe_request("GET", METRICS_KEY, query_params=qp,
                              timeout=15)
        body = str(raw) if raw is not None else ""
        print(f"[{tag}] status={s} bytes={len(body)} head={body[:200]!r}")
        return s, body

    def classify(tag, s, body):
        """Common 0/5xx/auth branches. Returns ENV/ENV_AUTH/None."""
        if s == 0:
            if not alive():
                return "ENV"
            DEFECTS.append(f"[{tag}] transport failure with /healthz alive — "
                           f"Type3_RuntimeFailure — exc={body[:150]}")
            return None
        if s in (401, 403):
            NOTES.append(f"[{tag}] auth-gated ({s}) mid-matrix — not "
                         f"adjudicable without credentials")
            return "ENV_AUTH"
        if 500 <= s <= 599:
            if alive():
                DEFECTS.append(f"[{tag}] answered {s} (5xx crash-class) with "
                               f"/healthz alive — Type3_RuntimeFailure — "
                               f"raw={body[:200]}")
                return None
            return "ENV"
        return None

    try:
        # ---- positive controls (G4: promise must hold before confusion) ----
        for tag, qp in [
            ("P0 bare", None),
            ("P1 anonymize=true", {"anonymize": "true"}),
            ("P2 per_collection=false", {"per_collection": "false"}),
        ]:
            s, body = leg(tag, qp)
            env = classify(tag, s, body)
            if env == "ENV":
                for n in NOTES:
                    print(f"NOTE: {n}")
                return "SCRIPT_ERROR"
            if env == "ENV_AUTH":
                for n in NOTES:
                    print(f"NOTE: {n}")
                return "SCRIPT_ERROR"
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
                    DEFECTS.append(f"[{tag}] positive control answered 200 "
                                   f"but body does not parse as Prometheus "
                                   f"text — Type4_StateLogicViolation — "
                                   f"raw={body[:200]}")
            else:
                DEFECTS.append(f"[{tag}] positive control answered {s} "
                               f"(non-2xx) on the live metrics face — "
                               f"Type4_StateLogicViolation — "
                               f"raw={body[:200]}")

        # ---- boolean confusion legs (strictly typed: Type1 if 200) ----
        for tag, key, val in BOOL_CONFUSION_LEGS:
            s, body = leg(tag, {key: val})
            env = classify(tag, s, body)
            if env == "ENV":
                for n in NOTES:
                    print(f"NOTE: {n}")
                return "SCRIPT_ERROR"
            if env == "ENV_AUTH":
                for n in NOTES:
                    print(f"NOTE: {n}")
                return "SCRIPT_ERROR"
            if 400 <= s <= 422 and s != 404:
                print(f"[{tag}] clean rejection ({s}) — documented boolean "
                      f"type enforced by serde — not a defect")
            elif 200 <= s <= 299:
                DEFECTS.append(f"[{tag}] non-boolean value {val!r} for the "
                               f"documented boolean param {key} answered "
                               f"{s} — Type1_IllegalSuccess candidate: the "
                               f"documented type constraint (v-1-18-x "
                               f"OpenAPI: {key}: boolean) was not enforced — "
                               f"judge weighs by-design-ignore (mirroring the "
                               f"threat model's filter=null note) — "
                               f"raw head={body[:120]!r}")
            elif s == 404:
                NOTES.append(f"[{tag}] 404 mid-matrix — face disappeared "
                             f"under confusion input; recorded")
            else:
                NOTES.append(f"[{tag}] unexpected status {s} — recorded for "
                             f"the judge — raw={body[:150]}")

        # ---- integer confusion legs (backfill provenance: NOTE on 200) ----
        for tag, key, val in INT_CONFUSION_LEGS:
            s, body = leg(tag, {key: val})
            env = classify(tag, s, body)
            if env == "ENV":
                for n in NOTES:
                    print(f"NOTE: {n}")
                return "SCRIPT_ERROR"
            if env == "ENV_AUTH":
                for n in NOTES:
                    print(f"NOTE: {n}")
                return "SCRIPT_ERROR"
            if 400 <= s <= 422 and s != 404:
                print(f"[{tag}] clean rejection ({s}) — documented integer "
                      f"type enforced — not a defect")
            elif 200 <= s <= 299:
                NOTES.append(f"DOC_CONSISTENCY_CANDIDATE [{tag}]: non-integer "
                             f"value {val!r} for the documented integer param "
                             f"{key} answered {s} — the param appears to be "
                             f"silently dropped by the handler; the OpenAPI "
                             f"provenance for this param is 'mechanical "
                             f"backfill' (raw_knowledge api_endpoints[metrics]"
                             f".parameters), so this is recorded for the "
                             f"judge rather than claimed Type1")
            elif s == 404:
                NOTES.append(f"[{tag}] 404 mid-matrix — recorded")
            else:
                NOTES.append(f"[{tag}] unexpected status {s} — recorded — "
                             f"raw={body[:150]}")

        # ---- api-key position-confusion leg (evidence-only) ----
        tag = "N12 api-key as query param"
        s, body = leg(tag, {"api-key": PFX + "not-a-real-key"})
        env = classify(tag, s, body)
        if env == "ENV":
            for n in NOTES:
                print(f"NOTE: {n}")
            return "SCRIPT_ERROR"
        if 200 <= s <= 299:
            NOTES.append(f"[{tag}] answered {s} with a bogus key as a query "
                         f"param — either no api-key auth is configured on "
                         f"this container (expected per round reflection) or "
                         f"the param is ignored where a header was "
                         f"documented; deployment-config dependent, not "
                         f"claimable")
        elif s in (401, 403):
            NOTES.append(f"[{tag}] answered {s} — auth IS configured and the "
                         f"bogus key was correctly rejected — legal")
        else:
            NOTES.append(f"[{tag}] status {s} — recorded for the judge — "
                         f"raw={body[:150]}")

        # ---- post-matrix control: the face must still keep the promise ----
        s, body = leg("post-matrix bare", None)
        env = classify("post-matrix bare", s, body)
        if env == "ENV":
            for n in NOTES:
                print(f"NOTE: {n}")
            return "SCRIPT_ERROR"
        if 200 <= s <= 299:
            h, t, n = prometheus_shape(body)
            if h + t < 1 or n < 1:
                DEFECTS.append(f"[post-matrix bare] face degraded after the "
                               f"confusion matrix: 200 body no longer parses "
                               f"as Prometheus text — Type3_RuntimeFailure "
                               f"(handler state corrupted by junk input)")
        elif not (400 <= s <= 499):
            DEFECTS.append(f"[post-matrix bare] answered {s} after the "
                           f"confusion matrix — face degraded — "
                           f"Type3_RuntimeFailure")

        for n in NOTES:
            print(f"NOTE: {n}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("metrics type-confusion matrix: positive controls kept the 200/"
              "Prometheus promise, every strictly-typed boolean confusion leg "
              "was cleanly rejected (or claimed where accepted), integer/"
              "position legs recorded with provenance caveats, face healthy "
              "afterwards — NO_DEFECT")
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
