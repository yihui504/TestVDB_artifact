#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_telemetry_003
# strategy: type_coercion
# endpoint: telemetry
# constraint_ids: qdrant_type_telemetry_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/service/telemetry
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust - integer/boolean query
#   parameters silently accepting float-shaped, bool-shaped, or int-shaped
#   wire values)
"""
Attack: type_coercion x constraints::qdrant_type_telemetry_001 (GET
  /telemetry, URL from raw_knowledge api_endpoints[telemetry].url). The
  endpoint types its query parameters: details_level integer (0..10),
  anonymize boolean, per_collection boolean (OpenAPI mechanical backfill in
  raw_knowledge). Hostile-typed wire values (BS-01):
    details_level=2.5  - float-shaped string; a lenient parser could floor
                         it into the 0..10 window and mask the violation,
    details_level=True - bool-shaped string; truthy-parsing would execute
                         an untyped verbosity level,
    per_collection=1   - int-shaped bool wire value; truthy coercion is the
                         classic REST boolean hole,
    anonymize=0        - int-shaped bool wire value (false direction).
  Wire-honesty note: per_collection="true" is byte-identical to
  per_collection=true in a query string, so it is not a valid probe and is
  not used; only shape-changing wire values are legs. Control-gated (R7
  lesson): the control no-param read must be 200 (this face is not
  distributed-mode-dependent), then each hostile leg must answer 4xx -
  a 200 means the server silently coerced a wrongly-typed wire value into
  the documented typed parameter (Type1_IllegalSuccess, BS-01); 5xx =
  Type3 with the /healthz recheck.
  [coverage: type_coercion x telemetry endpoint typed parameters
   (integer details_level vs float/bool shapes; boolean flags vs int shapes)]
Oracle: with control GET /telemetry = 200, the legs details_level=2.5,
  details_level=True, per_collection=1 and anonymize=0 each answer 4xx
  (typed parameters must not be implicitly coerced; a 200 =
  Type1_IllegalSuccess, 5xx with /healthz alive = Type3_RuntimeFailure);
  a non-200/non-4xx control = SCRIPT_ERROR honest exit (constraint
  qdrant_type_telemetry_001).

Rationale (G6/BS-01): details_level=2.5 is the maximal breaker - flooring
lands inside the documented 0..10 window so a lenient parser yields a
plausible success; the int-shaped boolean legs (per_collection=1,
anonymize=0) probe the opposite direction (integer accepted where a
boolean is declared), which is the shape most REST frameworks get wrong
via truthiness.
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
        # wrong-rejection of the bare control face is script semantic_telemetry_002's
        # declared defect; here it blocks param-level judgment -> honest exit
        script_error(f"control GET /telemetry status {cst}; cannot judge coercion legs")

    # ---- hostile-typed legs (integer param vs float/bool shapes; bool flags vs int shapes) ----
    legs = [
        ("details_level=2.5 (float-shaped; floors inside the 0..10 window)",
         {"details_level": 2.5}),
        ("details_level=True (bool-shaped truthy)", {"details_level": True}),
        ("per_collection=1 (int-shaped boolean)", {"per_collection": 1}),
        ("anonymize=0 (int-shaped boolean, false direction)", {"anonymize": 0}),
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
                   f"is alive; a hostile-typed parameter must be rejected cleanly, "
                   f"never crash; raw={str(raw)[:200]}")
        if 200 <= st < 300:
            defect("Type1_IllegalSuccess",
                   f"GET /telemetry accepted {tag} with {st}: the parameter is typed in "
                   f"the versioned contract (details_level integer 0..10; "
                   f"anonymize/per_collection boolean; constraint qdrant_type_telemetry_001 "
                   f"endpoint spec) - a 200 here means the server implicitly coerced a "
                   f"wrongly-typed wire value into the documented typed parameter "
                   f"(BS-01); raw={str(raw)[:250]}")
        if not (400 <= st < 500):
            script_error(f"unexpected status {st} on {tag}; no defect conclusion")
        print(f"[ok] {tag} refused cleanly with {st}")

    # ---- residue control: the documented face must be untouched after the matrix ----
    st2, raw2 = safe_request("GET", TELEMETRY_KEY, timeout=35)
    print(f"[residue control GET /telemetry] status={st2} raw={str(raw2)[:200]}")
    if st2 != 200:
        defect("Type4_StateLogicViolation",
               f"the documented 200 control read flipped to {st2} after the hostile-typed "
               f"matrix - refused inputs must leave zero trace on the face; "
               f"raw={str(raw2)[:250]}")

    print("[summary] every hostile-typed wire value (float/bool-shaped integer param, "
          "int-shaped boolean flags) was refused with a clean 4xx; no implicit type "
          "coercion; face intact after the matrix")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
