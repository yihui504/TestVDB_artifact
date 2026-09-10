#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_cluster_telemetry_003
# strategy: type_coercion
# endpoint: cluster+telemetry
# constraint_ids: qdrant_range_cluster_telemetry_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/cluster-telemetry
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust - an integer-typed query
#   parameter silently accepting float-shaped, bool-shaped, or non-numeric
#   wire values)
"""
Attack: type_coercion x constraints::qdrant_range_cluster_telemetry_001
  (chunk_cluster+telemetry; GET /cluster/telemetry?timeout=..., URL from
  raw_knowledge api_endpoints[cluster+telemetry].url). The constraint types
  timeout as integer (default 60, min 1); raw_knowledge/OpenAPI declares it
  an integer query parameter. Hostile-typed wire values (BS-01):
    timeout=1.5  - float-shaped string; a lenient parser could floor it to 1
                   (a legal value) and mask the type violation,
    timeout=True - bool-shaped string (Python bool serializes capitalized);
                   truthy-parsing would execute an untyped window,
    timeout=abc  - non-numeric string; only outright rejection is sane.
  Note (wire-honesty): a string "60" is byte-identical to integer 60 in a
  query string, so it is NOT a valid coercion probe and is not used.
  The matrix is control-gated (R7 lesson): a 200 no-param control read means
  param validation is actually reachable - each hostile leg must then be
  refused with 4xx (an accepted 200 = Type1_IllegalSuccess: the server
  silently coerced a non-integer into the documented integer window);
  a 4xx control (disabled face family, R6-R8) downgrades the judgment to
  uniform disposition only (a 2xx leg = G9 inconsistent execution =
  Type1_IllegalSuccess; 5xx = Type3; uniform 4xx = honest skip).
  [chunk_cluster+telemetry coverage: type_coercion x
   qdrant_range_cluster_telemetry_001 (integer-typed timeout vs
   float/bool/non-numeric wire values; control-gated)]
Oracle: with control GET /cluster/telemetry = 200, the legs timeout=1.5,
  timeout=True and timeout=abc each answer 4xx (integer-typed parameter
  must not be implicitly coerced; 200 = Type1_IllegalSuccess, 5xx with
  /healthz alive = Type3_RuntimeFailure); with a 4xx control, all legs
  answer 4xx uniformly (a 2xx leg = Type1_IllegalSuccess on a face that
  refuses its documented control) (constraint qdrant_range_cluster_telemetry_001).

Rationale (G6/BS-01): float-shaped 1.5 is the maximal breaker among the
hostile wire shapes - it is the only one whose coerced value (floor -> 1)
lands inside the documented legal window, so a lenient parser produces a
plausible-looking success that no one would question in production; the
bool and non-numeric legs bracket it with shapes no parser could mistake
for legal, isolating coercion (silent acceptance) from mere validation.
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


def safe_request(method, path_key, body=None, path_params=None, query_params=None,
                timeout=30):
    """All HTTP through the runtime; forwards method/path_key/body/path_params/
    query_params/timeout exactly (standing lesson). Returns (status, raw_text)."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


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

    # ---- hostile-typed legs (float-shaped / bool-shaped / non-numeric) ----
    legs = [
        ("timeout=1.5 (float-shaped; floors into the legal window)", 1.5),
        ("timeout=True (bool-shaped truthy)", True),
        ("timeout=abc (non-numeric)", "abc"),
    ]
    for tag, val in legs:
        qp = {"timeout": val}
        st, raw = safe_request("GET", CLUSTER_TELEMETRY_KEY, query_params=qp, timeout=35)
        print(f"[leg {tag}] status={st} raw={str(raw)[:300]}")
        if st == 0:
            liveness("transport")
            script_error(f"transport failure on {tag}; no defect conclusion")
        if 500 <= st <= 599:
            if liveness("5xx") != 200:
                script_error(f"5xx ({st}) on {tag} and /healthz not 200; deployment unstable")
            defect("Type3_RuntimeFailure",
                   f"GET /cluster/telemetry with {tag} raised server error {st} while "
                   f"/healthz is alive; a hostile-typed parameter must be rejected "
                   f"cleanly, never crash; raw={str(raw)[:200]}")

        if 200 <= cst < 300:
            if 200 <= st < 300:
                defect("Type1_IllegalSuccess",
                       f"GET /cluster/telemetry accepted {tag} with {st}: the timeout "
                       f"parameter is integer-typed (default 60, min 1) per constraint "
                       f"qdrant_range_cluster_telemetry_001 and the versioned OpenAPI - "
                       f"a 200 here means the server implicitly coerced a non-integer "
                       f"wire value into the documented window (BS-01); raw={str(raw)[:250]}")
            if not (400 <= st < 500):
                script_error(f"unexpected status {st} on {tag}; no defect conclusion")
            print(f"[ok] {tag} refused cleanly with {st}")
        else:
            # 4xx control (disabled face family): uniform-disposition judgment only
            if 200 <= st < 300:
                defect("Type1_IllegalSuccess",
                       f"G9 inconsistent execution on the disabled cluster telemetry face: "
                       f"the control read refuses {cst} but {tag} answers {st}; a disabled "
                       f"face must not execute hostile-typed variants; raw={str(raw)[:200]}")
            if not (400 <= st < 500):
                script_error(f"unexpected status {st} on {tag} with a {cst} control; no defect conclusion")
            print(f"[uniform] {tag} refused {st} like the control (disabled face family; "
                  f"param-validation judgment honestly skipped)")

    if 200 <= cst < 300:
        print("[summary] every hostile-typed timeout wire value was refused with a clean "
              "4xx on the live face - no implicit coercion of float/bool/non-numeric "
              "shapes into the integer-typed parameter")
    else:
        print("[summary] disabled-face control (4xx) refused all hostile-typed legs "
              "uniformly; coercion judgment honestly skipped (deployment-conditional "
              "family per R6-R8)")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
