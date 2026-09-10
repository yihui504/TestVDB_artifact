#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_create_018
# strategy: boundary (query-parameter minimum)
# endpoint: collections+create
# constraint_ids: qdrant_behavioral_collections_create_005
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 Boundary Default Optimism (timeout below the documented minimum 1
#   silently accepted is the named blindspot manifestation)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: boundary x qdrant_behavioral_collections_create_005 on collections+create (chunk_collections+create-2of2 unit assertions::qdrant_behavioral_collections_create_005)
Oracle: timeout=1 (the schema minimum itself, boundary closure) as a QUERY parameter
  -> 200 with envelope result:boolean==true (4xx on the min value = Type4 disposition
  conflict); timeout=0 / timeout=-1 / timeout=0.5 as QUERY parameters -> 4xx each
  (200 = Type1_IllegalSuccess: below-minimum silently accepted); 5xx with /healthz
  alive/dead = Type3; transport failure with healthy /healthz = SCRIPT_ERROR.
Unit detail: PUT /collections/{collection_name}; evidence_tier=explicit.
  The assertion's expected_behavior, quoted verbatim:
    "timeout values below 1 are rejected with an error, not silently accepted"

Parameter-placement check (v34 R1 lesson, restated by the runtime protocol): the spec
  declares timeout {in: query, type: integer, minimum: 1} - every probe is sent via
  query_params and NEVER in the body (a body-stuffed timeout is silently dropped and
  the measurement becomes vacuous).
Legs (G4 both directions, fresh collection name per leg so duplicate-name 409s cannot
  confound the adjudication):
  positive closure: timeout=1 (minimum accepted);
  negative: timeout=0 (below min), timeout=-1 (negative), timeout=0.5 (fractional -
    violates both the integer type and the minimum).
[chunk_collections+create-2of2 coverage: strategy6+1 x qdrant_resource_shard_number_001 =
  boundary_collections_create_013; envelope-positive x qdrant_behavioral_collections_create_001 =
  _014; duplicate-family x _002 = _015; enum/malformed x _003 = _016;
  cosine-normalization x _004 = _017; timeout-query x qdrant_behavioral_collections_create_005
  (this script); visibility chain x qdrant_bc_create_visibility_001 = _019]
Constraint: qdrant_behavioral_collections_create_005
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
doc_version: 1.18.x (versioned v-1-18-x api-reference)

R8-lesson spec-grid cross-check (BEFORE oracle): the versioned v-1-18-x merged OpenAPI
(.sourcedeps local shard openapi.json, path /collections/{collection_name}) declares
the timeout parameter verbatim as {"name":"timeout","in":"query","required":false,
"schema":{"type":"integer","minimum":1},"description":"Wait for operation commit timeout
in seconds. If timeout is reached - request will return with service error."} - so 1 is
min-closure and 0/-1/0.5 are schema violations. Response grid:
{status:string, time:number, result:boolean}.
"""
import os
import sys
import json
import time
import uuid
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
if not os.environ.get("TESTVDB_DB_URL"):
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)

PFX = "bcc18" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix
CREATED = []  # every attempted collection name; cleanup drops all (no list.remove)
DIM = 4
ASSERT = "timeout values below 1 are rejected with an error, not silently accepted"


def safe_request(method, path_key, **kw):
    """Thin delegation to rt.request (DB-neutral path_key; forwards body/path_params/
    query_params/timeout exactly - qdrant runtime protocol v2.3)."""
    return rt.request(method, path_key, **kw)


def healthz_ladder(label, attempts=3, delay=2):
    """G8 liveness re-check: inline safe_request('GET','healthz') probes, 3 attempts
    2s apart. Returns a bare Type3 message if the service is down, else None."""
    for i in range(attempts):
        hs, hraw = safe_request("GET", "healthz")
        print(f"[healthz attempt {i + 1}] status={hs} raw={str(hraw)[:120]}")
        if 200 <= hs < 300:
            return None
        if i < attempts - 1:
            time.sleep(delay)
    return (f"Type3_RuntimeFailure(service-down) - '{label}': /healthz unreachable "
            f"after {attempts} attempts")


def transport_gate(label, st, raw, findings):
    """Three-outcome isolation (G8): returns True if the leg is adjudicable,
    False after recording a transport/5xx finding."""
    if st <= 0:
        v = healthz_ladder(label)
        if v:
            findings.append((1, v))
        else:
            findings.append((3, f"SCRIPT-ERROR-transport: '{label}' failed with healthy /healthz: {str(raw)[:150]}"))
        return False
    if 500 <= st <= 599:
        v = healthz_ladder(label)
        findings.append((1, v if v else
                         f"Type3_RuntimeFailure: '{label}' got {st} with /healthz alive; body: {str(raw)[:200]}"))
        return False
    return True


def create_with_timeout(name, timeout_value):
    """timeout goes in the URL query string (spec: in query) - never the body."""
    return safe_request("PUT", "create_collection",
                        body={"vectors": {"size": DIM, "distance": "Cosine"}},
                        path_params={"name": name},
                        query_params={"timeout": timeout_value}, timeout=30)


def min_closure_leg(findings):
    """timeout=1 (the schema minimum) must be accepted - boundary closure."""
    label = "timeout=1 (schema minimum, closure)"
    name = PFX + "p" + str(len(CREATED))
    CREATED.append(name)
    st, raw = create_with_timeout(name, 1)
    print(f"[{label}] status={st} raw={str(raw)[:300]}")
    if not transport_gate(label, st, raw, findings):
        return
    v = rt.judge_200(st, raw, setup_ok=True)
    if v == "DEFECT_FOUND":
        findings.append((2, f"Type4 disposition conflict: '{label}' the documented minimum "
                            f"itself rejected with {st}; raw: {str(raw)[:200]}"))
        return
    try:
        env = json.loads(raw) if raw else {}
        ok_env = isinstance(env.get("result"), bool) and env["result"]
    except Exception:
        ok_env = False
    if ok_env:
        print(f"[conform] '{label}' accepted with 200 (envelope result:boolean=true)")
    else:
        findings.append((2, f"Type4_StateLogicViolation: '{label}' 200 but envelope "
                            f"violates result:boolean=true grid; raw: {str(raw)[:200]}"))


def below_min_leg(value, findings):
    label = f"timeout={value} (below schema minimum 1)"
    name = PFX + "n" + str(len(CREATED))
    CREATED.append(name)
    st, raw = create_with_timeout(name, value)
    print(f"[{label}] status={st} raw={str(raw)[:300]}")
    if not transport_gate(label, st, raw, findings):
        return
    v = rt.expect_rejected(st, raw, setup_ok=True)
    if v == "DEFECT_FOUND":
        findings.append((0, f"Type1_IllegalSuccess: '{label}' ACCEPTED with {st} - assertion "
                            f"requires rejection, not silent acceptance; raw: {str(raw)[:200]}"))
    elif v == "NO_DEFECT":
        print(f"[conform] '{label}' rejected with {st}")
    else:
        findings.append((3, f"SCRIPT-ERROR: '{label}' judge={v} status={st} raw={str(raw)[:150]}"))


def main():
    print(f"ownership prefix: {PFX}")
    print(f"[assertion quote] {ASSERT}")
    findings = []
    try:
        min_closure_leg(findings)
        below_min_leg(0, findings)
        below_min_leg(-1, findings)
        below_min_leg(0.5, findings)

        if findings:
            findings.sort(key=lambda x: x[0])
            rank, msg = findings[0]
            if rank == 3:
                print(f"VERDICT: SCRIPT_ERROR - {msg}")
                sys.exit(2)
            print(f"VERDICT: DEFECT_FOUND ({msg})")
            sys.exit(1)
        print("OK: timeout=1 min closure accepted; timeout=0/-1/0.5 rejected via the "
              "query parameter (no silent acceptance)")
        print("VERDICT: NO_DEFECT")
        sys.exit(0)
    finally:
        # data-bearing create endpoint: these collections are ours - drop best-effort
        for n in list(CREATED):
            try:
                rt.drop_collection(n)
            except Exception as e:
                print(f"cleanup warning (drop {n}): {e}")


if __name__ == "__main__":
    main()
