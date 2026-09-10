#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_telemetry_004
# strategy: diagnosis_quality
# endpoint: telemetry
# constraint_ids: qdrant_type_telemetry_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/service/telemetry
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-02 (Error Message Negligence - an out-of-window value refused
#   with an opaque body that names neither details_level nor the 0..10 range)
"""
Attack: diagnosis_quality (Type2 rubric) x
  constraints::qdrant_type_telemetry_001 (GET /telemetry, URL from
  raw_knowledge api_endpoints[telemetry].url). The endpoint documents
  details_level as integer "0..10 verbosity" (constraint + parameter
  description). Out-of-window legs:
    details_level=11 - exactly one above the documented maximum (the
                       boundary the 0..10 window exists to enforce),
    details_level=-1 - below the documented minimum.
  The semantic target is the DIAGNOSTIC QUALITY of the rejection (Round 2+
  focus): each leg must be refused (200 = the documented window is not
  enforced at all = Type1_IllegalSuccess), and each 4xx body is scored on
  the 3-criterion Type2 rubric - parameter_named ("details_level" in the
  message), format/range hint (must be/expected/should be/valid/range/
  minimum/at least/between/integer/positive), actionable hint (correct/try/
  use/change/specify/provide). Score 0 = Type2_PoorDiagnostics: an operator
  raising verbosity cannot tell which parameter or which side of the window
  failed. Control-gated on a 200 no-param read (this face is not
  distributed-mode-dependent).
  [coverage: diagnosis_quality (Type2 rubric) x telemetry endpoint
   details_level out-of-window rejections (acceptance + diagnostic quality)]
Oracle: with control GET /telemetry = 200, the legs details_level=11 and
  details_level=-1 answer 4xx (a 200 = Type1_IllegalSuccess - the
  documented 0..10 window not enforced; 5xx with /healthz alive =
  Type3_RuntimeFailure) and each 4xx body scores >= 1 on the Type2 rubric
  (param_named or format_hint or actionable; score 0 =
  Type2_PoorDiagnostics); a non-200 control = SCRIPT_ERROR honest exit
  (constraint qdrant_type_telemetry_001).

Rationale (G5/G7): the violation form is typed before measurement -
acceptance (Type1, window unenforced) vs opaque rejection (Type2, window
enforced but undiagnosable); "rejects with clear diagnostics" is the
non-defect exit, and the rubric dimensions (parameter_named=details_level,
format hint, actionable hint) are declared in the Oracle before any
response is seen.
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

FORMAT_HINTS = ["must be", "expected", "should be", "valid", "range", "type",
                "positive", "non-zero", "minimum", "at least", "between", "integer"]
ACTION_HINTS = ["correct", "try", "use", "change", "specify", "provide"]


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


def error_message(raw):
    """Extract the human-readable error text from a qdrant error body
    {"status": {"error": ...}} without assuming it (falls back to raw text)."""
    b = jload(raw)
    if isinstance(b, dict):
        node = b.get("status")
        if isinstance(node, dict) and node.get("error") is not None:
            return str(node.get("error"))
        if isinstance(node, str):
            return node
    return str(raw)


def check_error_quality(raw, expected_param):
    """Type2 rubric: parameter_named (1pt) + format/range hint (1pt) +
    actionable hint (1pt). Returns (score, named, fmt, act, message)."""
    msg = error_message(raw)
    low = msg.lower()
    named = expected_param.lower() in low
    fmt = any(h in low for h in FORMAT_HINTS)
    act = any(h in low for h in ACTION_HINTS)
    return int(named) + int(fmt) + int(act), named, fmt, act, msg


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

    # ---- control: the documented no-param service read must be 200 ----
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
    if cst != 200:
        script_error(f"control GET /telemetry status {cst}; cannot judge rubric legs "
                     "(the wrong-rejection of the bare control is semantic_telemetry_002's "
                     "declared defect)")

    legs = [
        ("details_level=11 (one above the documented maximum)", 11),
        ("details_level=-1 (below the documented minimum)", -1),
    ]
    for tag, val in legs:
        st, raw = safe_request("GET", TELEMETRY_KEY,
                               query_params={"details_level": val}, timeout=35)
        print(f"[leg {tag}] status={st} raw={str(raw)[:400]}")
        if st == 0:
            liveness("transport")
            script_error(f"transport failure on {tag}; no defect conclusion")
        if 500 <= st <= 599:
            if liveness("5xx") != 200:
                script_error(f"5xx ({st}) on {tag} and /healthz not 200; deployment unstable")
            defect("Type3_RuntimeFailure",
                   f"GET /telemetry with {tag} raised server error {st} while /healthz "
                   f"is alive; an out-of-window parameter must be refused cleanly, "
                   f"never crash; raw={str(raw)[:200]}")
        if 200 <= st < 300:
            defect("Type1_IllegalSuccess",
                   f"GET /telemetry accepted {tag} with {st}: details_level is the "
                   f"documented 0..10 verbosity integer (constraint "
                   f"qdrant_type_telemetry_001 endpoint spec) - the out-of-window value "
                   f"was silently served; raw={str(raw)[:250]}")
        if not (400 <= st < 500):
            script_error(f"unexpected status {st} on {tag}; no defect conclusion")
        score, named, fmt, act, msg = check_error_quality(raw, "details_level")
        print(f"  rubric: score={score}/3 (param_named={named}, format_hint={fmt}, "
              f"actionable={act}) on message={msg!r}")
        if score == 0:
            defect("Type2_PoorDiagnostics",
                   f"GET /telemetry with {tag} refused with {st} but the body is "
                   f"diagnostically empty: neither the parameter name 'details_level' "
                   f"nor any range/format/actionable hint appears in {msg!r}; an "
                   f"operator tuning the documented 0..10 verbosity window cannot tell "
                   f"what failed (BS-02); raw={str(raw)[:250]}")
        print(f"[ok] {tag} refused {st} with rubric score {score}/3")

    print("[summary] out-of-window details_level legs refused with diagnosable bodies "
          "(rubric >= 1); the documented 0..10 window is both enforced and explained")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
