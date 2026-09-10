#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_telemetry_002
# strategy: illegal_rejection
# endpoint: telemetry
# constraint_ids: qdrant_behavioral_telemetry_001, qdrant_type_telemetry_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/service/telemetry
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (boundary blindness on the documented 0..10 verbosity
#   window) + BS-05 (Documentation Drift - documented flags vs what the face
#   actually accepts)
"""
Attack: illegal_rejection (Type1 reverse) x
  assertions::qdrant_behavioral_telemetry_001 +
  constraints::qdrant_type_telemetry_001 (GET /telemetry, URL from
  raw_knowledge api_endpoints[telemetry].url). The assertion promises
  "HTTP 200 with full TelemetryData"; the endpoint documents query
  parameters details_level (integer, 0..10 verbosity), anonymize (boolean),
  per_collection (boolean). Legal-value closure legs (G4 positive):
    anonymize=true                            (documented boolean flag, true),
    per_collection=true                       (documented boolean flag, true),
    anonymize=true & per_collection=true & details_level=10 (combined-max
                                              legal combination),
    details_level=0                           (documented minimum - boundary
                                              closure demands the min itself
                                              be accepted),
    details_level=10                          (documented maximum - same
                                              closure at the top end).
  A control no-param read anchors the matrix (R7 lesson): /telemetry is the
  service-level face (not distributed-mode-dependent), so the control must
  be 200; every legal leg must then also answer 200 with an intact result
  envelope - any 4xx on a documented-legal value is
  Type1_IllegalRejection. Note timeout is deliberately NOT a judged leg
  here: its minimum/default are documented on the cluster+telemetry face's
  constraint, not on this endpoint's contract entry.
  [coverage: illegal_rejection x telemetry endpoint documented parameters
   (boolean flags + details_level min/max closure; control-gated)]
Oracle: with control GET /telemetry = 200, the legs anonymize=true,
  per_collection=true, anonymize+per_collection+details_level=10,
  details_level=0 and details_level=10 all answer HTTP 200 with a result
  object envelope (a 4xx on a documented-legal value =
  Type1_IllegalRejection; 5xx with /healthz alive = Type3_RuntimeFailure;
  200 with a missing/non-object result = Type4_StateLogicViolation; a 4xx
  control itself = Type1_IllegalRejection of the documented service face)
  (assertion qdrant_behavioral_telemetry_001, constraint
  qdrant_type_telemetry_001).

Rationale (G4): the five legs are exactly the parameter values a spec-
reading client sends on day one (both booleans on, both ends of the
verbosity window); refusing any of them is the highest-frequency
wrong-rejection shape for this endpoint, and the min/max legs close the
window's both boundaries rather than testing only its interior.
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

# ---- X1 bootstrap three-layer fallback: env -> upward walk -> contract target ----
_sd = os.environ.get("TESTVDB_SCRIPTS_DIR")
if not _sd:
    for _p in Path(__file__).resolve().parents:
        if (_p / "scripts" / "runtime" / "__init__.py").exists():
            _sd = str(_p)
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

if not os.environ.get("TESTVDB_DB_URL"):
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)

# ---- runtime PATHS gap: register the contract-derived URL (raw_knowledge only) ----
TELEMETRY_KEY = "telemetry"
if TELEMETRY_KEY not in rt.PATHS:
    rt.PATHS[TELEMETRY_KEY] = "/telemetry"
print(f"[path derivation] telemetry = {rt.PATHS[TELEMETRY_KEY]} "
      f"(raw_knowledge api_endpoints[telemetry].url)")


def safe_request(method, path_key, body=None, path_params=None, query_params=None,
                timeout=30):
    """All HTTP through the runtime; forwards method/path_key/body/path_params/
    query_params/timeout exactly (standing lesson). Returns (status, raw_text)."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def jload(raw):
    try:
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}


def script_error(msg):
    print(f"VERDICT: SCRIPT_ERROR - {msg}")
    sys.exit(2)


def defect(dtype, msg):
    print(f"VERDICT: DEFECT_FOUND ({dtype})")
    print(msg)
    sys.exit(1)


def liveness(tag):
    hs, hraw = safe_request("GET", "healthz")
    print(f"[{tag}] /healthz probe status={hs} raw={str(hraw)[:120]}")
    return hs


def main():
    hs, hraw = safe_request("GET", "healthz")
    print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
    if hs != 200:
        script_error(f"/healthz pre-probe returned {hs}; deployment not reachable")

    # ---- control: the documented no-param service read ----
    cst, craw = safe_request("GET", TELEMETRY_KEY, timeout=35)
    print(f"[control GET /telemetry] status={cst} raw={str(craw)[:300]}")
    if cst == 0:
        liveness("transport")
        script_error("transport failure on control read; no defect conclusion")
    if 500 <= cst <= 599:
        if liveness("5xx") != 200:
            script_error(f"control 5xx ({cst}) and /healthz not 200; deployment unstable")
        script_error(f"control GET /telemetry 5xx ({cst}) with /healthz alive; "
                     "face state unknown - no param-level conclusion")
    if 400 <= cst < 500:
        defect("Type1_IllegalRejection",
               f"the documented service telemetry face GET /telemetry refused with {cst} "
               f"on its plain no-param read; assertion qdrant_behavioral_telemetry_001 "
               f"promises 'HTTP 200 with full TelemetryData' and this face is not "
               f"distributed-mode-dependent (unlike the R6-R8 mutating cluster faces); "
               f"raw={str(craw)[:250]}")
    if not (200 <= cst < 300):
        script_error(f"unexpected control status {cst}; no defect conclusion")

    # ---- legal-value legs (documented booleans + details_level window closure) ----
    legs = [
        ("anonymize=true (documented boolean flag)", {"anonymize": True}),
        ("per_collection=true (documented boolean flag)", {"per_collection": True}),
        ("anonymize=true & per_collection=true & details_level=10 (combined legal max)",
         {"anonymize": True, "per_collection": True, "details_level": 10}),
        ("details_level=0 (documented minimum, boundary closure)", {"details_level": 0}),
        ("details_level=10 (documented maximum, boundary closure)", {"details_level": 10}),
    ]
    for tag, qp in legs:
        st, raw = safe_request("GET", TELEMETRY_KEY, query_params=qp, timeout=35)
        print(f"[leg {tag}] status={st} raw={str(raw)[:300]}")
        if st == 0:
            liveness("transport")
            script_error(f"transport failure on {tag}; no defect conclusion")
        if 500 <= st <= 599:
            if liveness("5xx") != 200:
                script_error(f"5xx ({st}) on {tag} and /healthz not 200; deployment unstable")
            defect("Type3_RuntimeFailure",
                   f"GET /telemetry with {tag} raised server error {st} while /healthz "
                   f"is alive; documented-legal parameters must be served, never crash; "
                   f"raw={str(raw)[:200]}")
        if 400 <= st < 500:
            defect("Type1_IllegalRejection",
                   f"GET /telemetry refused with {st} on {tag} although every value is "
                   f"documented-legal (details_level is the 0..10 verbosity integer, "
                   f"anonymize/per_collection are the documented boolean flags; assertion "
                   f"qdrant_behavioral_telemetry_001 promises 200 with full TelemetryData); "
                   f"raw={str(raw)[:250]}")
        if not (200 <= st < 300):
            script_error(f"unexpected status {st} on {tag}; no defect conclusion")
        b = jload(raw)
        res = b.get("result") if isinstance(b, dict) else None
        if not isinstance(res, dict):
            defect("Type4_StateLogicViolation",
                   f"{tag} answered 200 but the result node is missing/not an object "
                   f"(got {res!r}); legal parameterization must not break the "
                   f"TelemetryData envelope; raw={str(raw)[:250]}")
        print(f"[ok] {tag} served 200 with an intact result envelope "
              f"(sections={sorted(res.keys())[:12]}...)")

    print("[summary] all documented-legal parameter combinations (boolean flags on, "
          "details_level at both window boundaries and combined max) were served 200 "
          "with intact result envelopes; the legal parameter surface is honored")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
