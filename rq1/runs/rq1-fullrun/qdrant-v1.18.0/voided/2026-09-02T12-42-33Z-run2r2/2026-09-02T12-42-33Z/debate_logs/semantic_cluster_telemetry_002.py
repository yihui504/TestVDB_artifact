#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_cluster_telemetry_002
# strategy: illegal_rejection
# endpoint: cluster+telemetry
# constraint_ids: qdrant_range_cluster_telemetry_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/cluster-telemetry
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (boundary blindness on the documented timeout window) +
#   BS-05 (Documentation Drift - the documented default/minimum vs what the
#   face actually accepts)
"""
Attack: illegal_rejection (Type1 reverse) x
  constraints::qdrant_range_cluster_telemetry_001 (chunk_cluster+telemetry;
  GET /cluster/telemetry?timeout=..., URL from raw_knowledge
  api_endpoints[cluster+telemetry].url). The constraint (evidence_tier=
  explicit) declares the timeout query parameter "default 60, minimum 1".
  Legal-value closure legs (G4 positive):
    timeout=1  - the documented minimum itself; boundary closure demands the
                 min value be ACCEPTED, not one-past-it only,
    timeout=2  - an interior legal value,
    timeout=60 - the documented default made explicit (the value the server
                 uses when the parameter is omitted must be accepted when
                 spelled out).
  A control no-param read anchors the matrix (R7 lesson): if the control is
  200, every legal leg must also be 200 - any 4xx on a documented-legal
  value is Type1_IllegalRejection (a caller spelling out the documented
  default or the documented minimum gets refused). If the control is a 4xx
  (the standalone-deployment disabled face family from R6-R8), the legs are
  judged only for uniform disposition: a legal-value leg answering 2xx while
  the control refuses is a G9 inconsistent execution = Type1_IllegalSuccess;
  5xx on any leg = Type3; uniform 4xx = deployment-conditional family,
  param-level judgment honestly skipped.
  [chunk_cluster+telemetry coverage: illegal_rejection x
   qdrant_range_cluster_telemetry_001 (timeout min-closure + default +
   interior legal value; control-gated matrix)]
Oracle: with control GET /cluster/telemetry = 200, every leg
  timeout=1/timeout=2/timeout=60 also returns HTTP 200 (a 4xx on a
  documented-legal timeout = Type1_IllegalRejection, 5xx with /healthz
  alive = Type3_RuntimeFailure, envelope result object still present);
  with a 4xx control, every leg answers 4xx uniformly (a 2xx leg =
  Type1_IllegalSuccess - executing on a face that refuses the documented
  control read) (constraint qdrant_range_cluster_telemetry_001).

Rationale (G4/G7): the range constraint's promise is bidirectional - it
bounds the legal window AND promises everything inside it is served; the
min-value and default-value legs are the two values a spec-reading client
is most likely to spell out, so refusing them is the highest-frequency
wrong-rejection shape for this parameter.
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

    # ---- legal-value legs: documented minimum, interior value, documented default ----
    legs = [
        ("timeout=1 (documented minimum, boundary closure)", {"timeout": 1}),
        ("timeout=2 (interior legal value)", {"timeout": 2}),
        ("timeout=60 (documented default, explicit)", {"timeout": 60}),
    ]
    for tag, qp in legs:
        # timeout=60 may legitimately wait up to 60s server-side -> generous transport
        t = 70 if qp.get("timeout") == 60 else 35
        st, raw = safe_request("GET", CLUSTER_TELEMETRY_KEY, query_params=qp, timeout=t)
        print(f"[leg {tag}] status={st} raw={str(raw)[:300]}")
        if st == 0:
            liveness("transport")
            script_error(f"transport failure on {tag}; no defect conclusion")
        if 500 <= st <= 599:
            if liveness("5xx") != 200:
                script_error(f"5xx ({st}) on {tag} and /healthz not 200; deployment unstable")
            defect("Type3_RuntimeFailure",
                   f"GET /cluster/telemetry with {tag} raised server error {st} while "
                   f"/healthz is alive; constraint qdrant_range_cluster_telemetry_001 "
                   f"documents timeout default 60 min 1 - the legal window must be served, "
                   f"never crash; raw={str(raw)[:200]}")

        if 200 <= cst < 300:
            if 400 <= st < 500:
                defect("Type1_IllegalRejection",
                       f"GET /cluster/telemetry?{tag} refused with {st} although the control "
                       f"no-param read answers {cst}; constraint "
                       f"qdrant_range_cluster_telemetry_001 declares timeout minimum 1 / "
                       f"default 60 - a documented-legal value (and the explicit default) "
                       f"must be accepted; raw={str(raw)[:250]}")
            if not (200 <= st < 300):
                script_error(f"unexpected status {st} on {tag}; no defect conclusion")
            b = jload(raw)
            res = b.get("result") if isinstance(b, dict) else None
            if not isinstance(res, dict):
                defect("Type4_StateLogicViolation",
                       f"{tag} answered 200 but the result node is missing/not an object "
                       f"(got {res!r}); the telemetry payload envelope must survive legal "
                       f"parameterization; raw={str(raw)[:250]}")
        else:
            # 4xx control (disabled face family): only uniform disposition is judgeable
            if 200 <= st < 300:
                defect("Type1_IllegalSuccess",
                       f"G9 inconsistent execution on the disabled cluster telemetry face: "
                       f"the control no-param read refuses {cst} but {tag} executes {st}; "
                       f"a face that refuses its documented control must not execute "
                       f"parameterized variants; raw={str(raw)[:200]}")
            if not (400 <= st < 500):
                script_error(f"unexpected status {st} on {tag} with a {cst} control; no defect conclusion")

    if 200 <= cst < 300:
        print("[summary] documented-legal timeout values 1/2/60 all served 200 with an "
              "intact result envelope; the constraint's legal window is honored in both "
              "directions (min closed, default accepted)")
    else:
        print("[summary] disabled-face control (4xx) refused all legal-timeout legs "
              "uniformly; param-level acceptance judgment honestly skipped "
              "(deployment-conditional family per R6-R8; uniform disposition held)")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
