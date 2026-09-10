#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_cluster_telemetry_004
# strategy: diagnosis_quality
# endpoint: cluster+telemetry
# constraint_ids: qdrant_range_cluster_telemetry_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/cluster-telemetry
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-02 (Error Message Negligence - a below-minimum value refused
#   with an opaque body that names neither the parameter nor the valid range)
"""
Attack: diagnosis_quality (Type2 rubric) x
  constraints::qdrant_range_cluster_telemetry_001 (chunk_cluster+telemetry;
  GET /cluster/telemetry?timeout=..., URL from raw_knowledge
  api_endpoints[cluster+telemetry].url). The constraint documents timeout
  "default 60, minimum 1". Below-window legs:
    timeout=0  - exactly one below the documented minimum (the boundary the
                 range constraint exists to enforce),
    timeout=-1 - the signed-invalid direction (tests whether the parser
                 reports the range or merely a type error).
  The semantic target is the DIAGNOSTIC QUALITY of the rejection (Round 2+
  focus), not the rejection itself: each leg must be refused (200 = the
  below-minimum window was accepted = Type1_IllegalSuccess - the range half
  of the constraint is simply not enforced), and each 4xx body is scored on
  the 3-criterion Type2 rubric: parameter_named ("timeout" appears in the
  message) + format/range hint (must be/expected/should be/valid/range/
  minimum/at least/between/integer/positive) + actionable hint (correct/
  try/use/change/specify/provide). Score 0 = an opaque refusal body
  ("Bad request" with nothing else) = Type2_PoorDiagnostics: an operator
  tuning the telemetry wait window cannot tell which parameter or which
  side of the window failed. Control-gated: on a 4xx (disabled face)
  control the refusal is face-level, not param-level, so the rubric is
  honestly skipped and only uniform disposition is judged.
  [chunk_cluster+telemetry coverage: diagnosis_quality (Type2 rubric) x
   qdrant_range_cluster_telemetry_001 (below-minimum timeout rejections:
   acceptance + diagnostic quality)]
Oracle: with control GET /cluster/telemetry = 200, the legs timeout=0 and
  timeout=-1 answer 4xx (a 200 = Type1_IllegalSuccess - documented minimum 1
  not enforced; 5xx with /healthz alive = Type3_RuntimeFailure) and each 4xx
  body scores >= 1 on the Type2 rubric (param_named or format_hint or
  actionable; score 0 = Type2_PoorDiagnostics); with a 4xx control all legs
  answer 4xx uniformly (2xx leg = Type1_IllegalSuccess; rubric skipped as
  face-level) (constraint qdrant_range_cluster_telemetry_001).

Rationale (G5/G7): the violation form is typed two ways before judging -
acceptance (Type1, range unenforced) vs opaque rejection (Type2, range
enforced but undiagnosable); "rejects with clear diagnostics" is the
non-defect exit, so the rubric must be declared before the measurement
(parameter_named=timeout, format hint, actionable hint).
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
CLUSTER_TELEMETRY_KEY = "cluster_telemetry"
if CLUSTER_TELEMETRY_KEY not in rt.PATHS:
    rt.PATHS[CLUSTER_TELEMETRY_KEY] = "/cluster/telemetry"
print(f"[path derivation] cluster_telemetry = {rt.PATHS[CLUSTER_TELEMETRY_KEY]} "
      f"(raw_knowledge api_endpoints[cluster+telemetry].url)")

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

    # ---- control: the documented no-param read anchors the matrix ----
    cst, craw = safe_request("GET", CLUSTER_TELEMETRY_KEY, timeout=35)
    print(f"[control GET /cluster/telemetry] status={cst} raw={str(craw)[:300]}")
    if cst == 0:
        liveness("transport")
        script_error("transport failure on control read; no defect conclusion")
    if 500 <= cst <= 599:
        if liveness("5xx") != 200:
            script_error(f"control 5xx ({cst}) and /healthz not 200; deployment unstable")
        script_error(f"control GET /cluster/telemetry 5xx ({cst}) with /healthz alive; "
                     "face state unknown - no param-level conclusion")
    if not (200 <= cst < 300 or 400 <= cst < 500):
        script_error(f"unexpected control status {cst}; no defect conclusion")

    legs = [
        ("timeout=0 (one below the documented minimum)", 0),
        ("timeout=-1 (signed-invalid direction)", -1),
    ]
    for tag, val in legs:
        st, raw = safe_request("GET", CLUSTER_TELEMETRY_KEY,
                               query_params={"timeout": val}, timeout=35)
        print(f"[leg {tag}] status={st} raw={str(raw)[:400]}")
        if st == 0:
            liveness("transport")
            script_error(f"transport failure on {tag}; no defect conclusion")
        if 500 <= st <= 599:
            if liveness("5xx") != 200:
                script_error(f"5xx ({st}) on {tag} and /healthz not 200; deployment unstable")
            defect("Type3_RuntimeFailure",
                   f"GET /cluster/telemetry with {tag} raised server error {st} while "
                   f"/healthz is alive; a below-minimum parameter must be refused "
                   f"cleanly, never crash; raw={str(raw)[:200]}")

        if 200 <= cst < 300:
            if 200 <= st < 300:
                defect("Type1_IllegalSuccess",
                       f"GET /cluster/telemetry accepted {tag} with {st}: constraint "
                       f"qdrant_range_cluster_telemetry_001 documents timeout minimum 1 - "
                       f"the below-minimum window was silently served; raw={str(raw)[:250]}")
            if not (400 <= st < 500):
                script_error(f"unexpected status {st} on {tag}; no defect conclusion")
            score, named, fmt, act, msg = check_error_quality(raw, "timeout")
            print(f"  rubric: score={score}/3 (param_named={named}, format_hint={fmt}, "
                  f"actionable={act}) on message={msg!r}")
            if score == 0:
                defect("Type2_PoorDiagnostics",
                       f"GET /cluster/telemetry with {tag} refused with {st} but the body "
                       f"is diagnostically empty: neither the parameter name 'timeout' nor "
                       f"any range/format/actionable hint appears in {msg!r}; an operator "
                       f"tuning the documented wait window cannot tell what failed "
                       f"(BS-02); raw={str(raw)[:250]}")
            print(f"[ok] {tag} refused {st} with rubric score {score}/3")
        else:
            # 4xx control (disabled face family): face-level refusal - rubric invalid
            if 200 <= st < 300:
                defect("Type1_IllegalSuccess",
                       f"G9 inconsistent execution on the disabled cluster telemetry face: "
                       f"the control read refuses {cst} but {tag} answers {st}; raw="
                       f"{str(raw)[:200]}")
            if not (400 <= st < 500):
                script_error(f"unexpected status {st} on {tag} with a {cst} control; no defect conclusion")
            print(f"[uniform] {tag} refused {st} like the control; the refusal is "
                  f"face-level (Distributed-mode family per R6-R8), so the param rubric "
                  f"is honestly skipped for this leg")

    if 200 <= cst < 300:
        print("[summary] below-minimum timeout legs refused with diagnosable bodies "
              "(rubric >= 1); the documented minimum is both enforced and explained")
    else:
        print("[summary] disabled-face control (4xx) refused all below-minimum legs "
              "uniformly; rubric honestly skipped (deployment-conditional family)")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
