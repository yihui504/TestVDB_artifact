#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 parameter-domain attack + strategy2 type-confusion attack
  on the documented query parameters of telemetry (GET /telemetry) x the
  payload promise of qdrant_behavioral_telemetry_001 (evidence_tier
  explicit), whose expected_behavior, quoted verbatim:
    "HTTP 200 with TelemetryData payload"
  R8-lesson cross-check performed BEFORE writing the oracle (versioned
  v-1-18-x OpenAPI, path /telemetry):
    details_level: {type: integer, minimum: 0}, description "Level of details
      in telemetry data. Minimal level is 0, maximal is infinity" — so 0 is
      the min-closure leg (claimed 200) and -1 the below-minimum leg (claimed
      4xx); 10 is in-domain on BOTH readings (spec: unbounded; contract
      record paraphrase: '0..10 verbosity') -> claimed 200; 11 is the
      divergence leg: the PUBLISHED SPEC explicitly says "maximal is
      infinity", so a 4xx there rejects a spec-legal value = claimed defect
      (Type4), judge-annotated with the record's conflicting '0..10'
      paraphrase;
    anonymize / per_collection: {type: boolean} — documented true forms are
      positive payload legs; the token 'maybe' is type-invalid -> claimed 4xx
      (2xx = Type1 silent coercion).
  The 200-payload promise is checked on every positive leg (envelope +
  result.id:string + result.collections:object — the schema-required core).
[coverage: /telemetry endpoint of this round per dispatch NOTE; strategy1
 param-domain + strategy2 param-typing x qdrant_behavioral_telemetry_001
 positive face; the 9-section grid face of the same endpoint is covered by
 boundary_telemetry_001; timeout cross-face disposition by
 boundary_telemetry_003]
Oracle: details_level in {0,10} and boolean params true -> 200 each with
  envelope + result.id:string + result.collections:object (promise holds on
  every documented form); details_level=-1 -> 4xx (schema minimum:0; 2xx =
  DEFECT Type1_IllegalSuccess); details_level=11 -> 2xx per the published
  'maximal is infinity', 4xx = DEFECT_FOUND (Type4 — spec-legal level
  rejected; judge-annotated re the record's '0..10' paraphrase conflict);
  anonymize='maybe' / per_collection='maybe' -> 4xx each (2xx = DEFECT
  Type1_IllegalSuccess); 5xx anywhere (with /healthz rechecked alive) =
  DEFECT (Type3_RuntimeFailure); positive-leg payload broken = DEFECT
  (Type4_StateLogicViolation); transport failure with healthy /healthz =
  SCRIPT_ERROR.
Constraint: qdrant_behavioral_telemetry_001
Blindspot: BS-04 Boundary Default Optimism (a detail-level enum capped
  below its own published 'maximal is infinity' promise) + BS-01 Parameter
  Type Coercion Trust (boolean query params coerced from arbitrary tokens)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/service/telemetry
doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""

import json
import os
import sys
import time
import uuid
from pathlib import Path

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# --- X1 bootstrap: three-layer fallback (env -> upward walk -> contract target) ---
BASE_URL = os.environ.get("TESTVDB_DB_URL")
TARGET = os.environ.get("TESTVDB_TARGET", "")
if not TARGET:
    _root = Path(__file__).resolve()
    for _p in (_root, *list(_root.parents)):
        _f = _p / "structured_contract.json"
        if _f.exists():
            try:
                _c = json.loads(_f.read_text(encoding="utf-8"))
                TARGET = _c.get("target", "") or TARGET
            except Exception:
                pass
            break
if not BASE_URL or TARGET != "qdrant":
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL/TESTVDB_TARGET missing (bootstrap fallback failed)")
    sys.exit(2)

AUTH_HEADER = os.environ.get("TESTVDB_AUTH_HEADER", "")


def derive_url(path_key):
    """R5/R6 standing lesson: URLs come only from raw_knowledge api_endpoints[].url."""
    for _p in Path(__file__).resolve().parents:
        _rk = _p / "raw_knowledge.json"
        if _rk.exists():
            try:
                for _e in json.loads(_rk.read_text(encoding="utf-8")).get("api_endpoints", []):
                    if _e.get("path") == path_key and _e.get("url"):
                        return _e["url"]
            except Exception:
                return None
            return None
    return None


TELEMETRY_URL = derive_url("telemetry")
if not TELEMETRY_URL:
    print("VERDICT: SCRIPT_ERROR — url not derivable from raw_knowledge api_endpoints[].url (telemetry)")
    sys.exit(2)
print(f"[url-derived] telemetry -> {TELEMETRY_URL}")


def safe_request(method, endpoint, json=None, params=None, data=None, timeout=10):
    """
    Safe HTTP request wrapper with unified error handling (agents/_target_api_reference.md).
    Returns: (status_code, body, raw_text)
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    if AUTH_HEADER:
        headers["Authorization"] = AUTH_HEADER
    try:
        response = requests.request(
            method=method, url=url, json=json, params=params,
            data=data, headers=headers, timeout=timeout,
        )
        status_code = response.status_code
        raw_text = response.text
        try:
            body = response.json()
        except Exception:
            body = raw_text
        return status_code, body, raw_text
    except Exception as e:
        return -1, str(e), str(e)


def healthz_ladder(label, attempts=3, delay=2):
    """G8 liveness re-check: /healthz gets 3 attempts 2s apart before any Type3
    conclusion (transport-branch probe; standing lesson)."""
    for i in range(attempts):
        hs, _, hraw = safe_request("GET", "/healthz", timeout=5)
        print(f"[healthz attempt {i + 1}] status={hs} raw={str(hraw)[:120]}")
        if 200 <= hs < 300:
            return None
        if i < attempts - 1:
            time.sleep(delay)
    # NOTE: returns a BARE Type3 message (no DEFECT_FOUND prefix — the caller's
    # verdict wrapper adds it exactly once).
    return (f"Type3_RuntimeFailure(service-down) — '{label}': /healthz unreachable "
            f"after {attempts} attempts")


def parse_body(raw, body):
    try:
        return json.loads(raw) if isinstance(raw, str) else (body if isinstance(body, dict) else {})
    except Exception:
        return {}


def payload_violation(node):
    """Promise check on a positive 2xx leg: envelope + schema-required core."""
    if not isinstance(node.get("status"), str):
        return "envelope status not a string"
    if not (isinstance(node.get("time"), (int, float)) and not isinstance(node.get("time"), bool)):
        return "envelope time not a number"
    result = node.get("result")
    if not isinstance(result, dict):
        return "envelope result not an object (TelemetryData)"
    if not isinstance(result.get("id"), str):
        return "result.id not a string (schema-required TelemetryData field)"
    if not isinstance(result.get("collections"), dict):
        return "result.collections not an object (schema-required TelemetryData field)"
    return None


def main():
    tag = uuid.uuid4().hex[:8]
    print(f"ownership tag: btl2-{tag}")
    print("[expected_behavior quote] HTTP 200 with TelemetryData payload")
    print("[domain sources] published OpenAPI: details_level {integer, minimum:0, "
          "'minimal level is 0, maximal is infinity'}; anonymize/per_collection "
          "{boolean}; contract record paraphrase '0..10 verbosity' recorded as the "
          "conflicting layer")

    findings = []  # (rank, message); 0 = Type3, 1 = Type1, 2 = Type4, 3 = script-error

    def run_leg(label, params, expect):
        """expect: '2xx-payload' | '4xx' | '2xx-spec-legal'"""
        s, b, r = safe_request("GET", TELEMETRY_URL, params=params, timeout=15)
        print(f"[{label}] params={params} status={s} raw={str(r)[:280]}")
        if s <= 0:
            v = healthz_ladder(label)
            return (0, v) if v else (3, f"SCRIPT-ERROR-transport: '{label}' with healthy /healthz")
        if 500 <= s <= 599:
            v = healthz_ladder(label)
            return (0, v if v else f"Type3_RuntimeFailure: '{label}' got {s} with /healthz alive; body: {str(r)[:200]}")
        if 200 <= s <= 299:
            if expect == "4xx":
                return (1, f"Type1_IllegalSuccess: '{label}' ACCEPTED with {s} — documented "
                          f"domain/type violation silently admitted; raw: {str(r)[:200]}")
            bad = payload_violation(parse_body(r, b))
            if bad:
                return (2, f"Type4_StateLogicViolation: '{label}' 200 but payload promise broken: "
                          f"{bad}; raw: {str(r)[:200]}")
            print(f"[conform] '{label}' 200 with TelemetryData payload core")
            return None
        if 400 <= s <= 499:
            if expect == "2xx-payload":
                return (2, f"Type4 disposition conflict: '{label}' (documented-legal form) rejected "
                          f"with {s}; raw: {str(r)[:200]}")
            if expect == "2xx-spec-legal":
                return (2, f"Type4 disposition conflict: '{label}' rejected with {s} — the published "
                          f"v-1-18-x spec documents details_level as 'minimal level is 0, maximal is "
                          f"infinity' (integer, minimum:0, NO maximum), so this value is spec-legal; "
                          f"NOTE(judge): the contract record's '0..10 verbosity' paraphrase conflicts "
                          f"with the published spec — claim anchored on the spec per D3b "
                          f"(spec-derived wins); raw: {str(r)[:200]}")
            print(f"[conform] '{label}' rejected with {s}")
            return None
        return (3, f"SCRIPT-ERROR-status: '{label}' uninterpreted status {s}")

    legs = [
        ("details_level=0 (min closure)", {"details_level": 0}, "2xx-payload"),
        ("details_level=10 (in-domain on both readings)", {"details_level": 10}, "2xx-payload"),
        ("details_level=-1 (below schema minimum:0)", {"details_level": -1}, "4xx"),
        ("details_level=11 (spec-legal: 'maximal is infinity')", {"details_level": 11}, "2xx-spec-legal"),
        ("anonymize=true (documented boolean form)", {"anonymize": "true"}, "2xx-payload"),
        ("per_collection=true (documented boolean form)", {"per_collection": "true"}, "2xx-payload"),
        ("anonymize='maybe' (type-invalid boolean token)", {"anonymize": "maybe"}, "4xx"),
        ("per_collection='maybe' (type-invalid boolean token)", {"per_collection": "maybe"}, "4xx"),
    ]
    for label, params, expect in legs:
        f = run_leg(label, params, expect)
        if f:
            findings.append(f)

    if findings:
        findings.sort(key=lambda x: x[0])
        rank, msg = findings[0]
        if rank == 3:
            print(f"VERDICT: SCRIPT_ERROR — {msg}")
        else:
            print(f"VERDICT: DEFECT_FOUND ({msg})")
        return
    print("OK: documented forms serve the payload promise; below-minimum and "
          "type-invalid tokens rejected; unbounded spec-legal level honored")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
