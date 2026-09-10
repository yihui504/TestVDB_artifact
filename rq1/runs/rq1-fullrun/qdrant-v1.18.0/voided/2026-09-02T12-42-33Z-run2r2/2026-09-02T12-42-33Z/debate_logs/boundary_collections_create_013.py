#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_create_013
# strategy: boundary + resource_limit (strategy 1 closure + strategy 6)
# endpoint: collections+create
# constraint_ids: qdrant_resource_shard_number_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 Boundary Default Optimism (shard_number=0/-1 below documented
#   minimum 1 accepted silently is the named blindspot manifestation)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy6+1 x qdrant_resource_shard_number_001 on collections+create (chunk_collections+create-2of2 unit constraints::qdrant_resource_shard_number_001)
Oracle: shard_number=0/-1 -> 4xx (200 = Type1_IllegalSuccess: below documented minimum 1);
  shard_number=1 (documented min, boundary closure) -> 200 with envelope result:true and
  describe readback result.config.params.shard_number==1 (any other readback = Type4);
  spec-legal large shard_number (1000 / 100000 / 4294967295 = uint32 max) -> 200 (completed,
  readback must equal sent) or 4xx (rejected) - 5xx/OOM/panic or /healthz death = Type3
  (5xx-with-alive-healthz body printed for the judge to weigh the constraint's
  documented-service-error clause); transport failure with healthy /healthz = SCRIPT_ERROR.
Unit detail: PUT /collections/{collection_name}; type=resource_bound, level=system,
  evidence_tier=inferred. The constraint's assertion, quoted verbatim:
    "inferred: any spec-legal shard_number (>= 1, no documented max) must be completed,
     rejected with an error, or fail with a documented service error - never crash the service"

Legs (G4 both directions, fresh collection per leg; G6 mutation rationale inline):
  negative boundary (BS-04): shard_number=0 (shard routing space sized by zero - classic
    allocator/divisor boundary), shard_number=-1 (uint domain violation);
  positive closure: shard_number=1 (the documented minimum itself must be accepted);
  resource legs (strategy 6 - the contract boundary has no max, the implementation limit
    is the unknown): shard_number=1000 (plausibly completes - verifies the "completed"
    branch), 100000 (1e5 - resource strain), 4294967295 (UINT32_MAX, largest spec-legal
    uint32 value - maximum allocation request the schema admits).
[chunk_collections+create-2of2 coverage: strategy6+1 x qdrant_resource_shard_number_001
  (this script); envelope-positive x qdrant_behavioral_collections_create_001 =
  boundary_collections_create_014; duplicate-family x _002 = _015; enum/malformed x _003
  = _016; cosine-normalization x _004 = _017; timeout-query x _005 = _018; visibility
  chain x qdrant_bc_create_visibility_001 = _019]
Constraint: qdrant_resource_shard_number_001
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
doc_version: 1.18.x (versioned v-1-18-x api-reference)

R8-lesson spec-grid cross-check (BEFORE oracle): the versioned v-1-18-x merged OpenAPI
(.sourcedeps local shard openapi.json, path /collections/{collection_name}, schema
CreateCollection) declares shard_number {"type":["integer","null"],"format":"uint",
"Minimum is 1", "Default is 1 for standalone"} with NO maximum - so 0/-1 are below-min
violations, 1 is min-closure, and any uint32 up to 4294967295 is spec-legal (the
constraint's premise). Response grid: {status:string, time:number, result:boolean};
describe readback path result.config.params.shard_number.
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

PFX = "bcc13" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix
CREATED = []  # every attempted collection name; cleanup drops all (no list.remove)
DIM = 4
ASSERT = ("any spec-legal shard_number (>= 1, no documented max) must be completed, "
          "rejected with an error, or fail with a documented service error - never crash the service")


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
                         f"Type3_RuntimeFailure-signal: '{label}' got {st} with /healthz alive; "
                         f"body (judge to weigh the constraint's documented-service-error clause): {str(raw)[:250]}"))
        return False
    return True


def create(name, body, timeout=60):
    return safe_request("PUT", "create_collection", body=body,
                        path_params={"name": name}, timeout=timeout)


def describe_result(name, timeout=90):
    st, raw = safe_request("GET", "describe_collection",
                           path_params={"name": name}, timeout=timeout)
    if st != 200:
        return None, f"describe {st}: {str(raw)[:150]}"
    try:
        return json.loads(raw).get("result"), None
    except Exception as e:
        return None, f"envelope:{e}"


def walk(node, path):
    for k in path:
        if isinstance(node, dict):
            node = node.get(k)
        else:
            return None
    return node


def envelope_result_true(raw):
    try:
        env = json.loads(raw) if raw else {}
    except Exception:
        return False
    return isinstance(env, dict) and isinstance(env.get("result"), bool) and env["result"]


def new_name(tag):
    name = PFX + tag + str(len(CREATED))
    CREATED.append(name)
    return name


def below_min_leg(value, findings):
    """Strategy 1 negative boundary (BS-04): shard_number below documented minimum 1."""
    label = f"shard_number={value}"
    name = new_name("n")
    st, raw = create(name, {"vectors": {"size": DIM, "distance": "Cosine"},
                            "shard_number": value})
    print(f"[{label}] status={st} raw={str(raw)[:300]}")
    if not transport_gate(label, st, raw, findings):
        return
    v = rt.expect_rejected(st, raw, setup_ok=True)
    if v == "DEFECT_FOUND":
        findings.append((0, f"Type1_IllegalSuccess: '{label}' ACCEPTED with {st} - spec "
                            f"declares Minimum is 1 (format uint); raw: {str(raw)[:200]}"))
    elif v == "NO_DEFECT":
        print(f"[conform] '{label}' rejected with {st}")
    else:
        findings.append((3, f"SCRIPT-ERROR: '{label}' judge={v} status={st} raw={str(raw)[:150]}"))


def min_closure_leg(findings):
    """Strategy 1 positive closure: the documented minimum itself must be accepted."""
    label = "shard_number=1 (documented min, boundary closure)"
    name = new_name("p")
    st, raw = create(name, {"vectors": {"size": DIM, "distance": "Cosine"},
                            "shard_number": 1})
    print(f"[{label}] status={st} raw={str(raw)[:300]}")
    if not transport_gate(label, st, raw, findings):
        return
    v = rt.judge_200(st, raw, setup_ok=True)
    if v == "DEFECT_FOUND":
        findings.append((2, f"Type4 disposition conflict: '{label}' documented-legal value "
                            f"rejected with {st}; raw: {str(raw)[:200]}"))
        return
    if not envelope_result_true(raw):
        findings.append((2, f"Type4_StateLogicViolation: '{label}' 200 but envelope violates "
                            f"result:boolean=true grid; raw: {str(raw)[:200]}"))
        return
    res, err = describe_result(name)
    got = walk(res, ["config", "params", "shard_number"]) if isinstance(res, dict) else None
    if got == 1:
        print(f"[conform] '{label}' 200; readback config.params.shard_number={got!r}")
    else:
        findings.append((2, f"Type4_StateLogicViolation: '{label}' accepted but readback "
                            f"config.params.shard_number={got!r} != sent 1 ({err or ''})"))


def resource_leg(value, http_timeout, findings):
    """Strategy 6 resource leg: spec-legal (no documented max) shard_number must be
    completed (200, readback==sent), rejected (4xx), or a documented service error -
    never a crash (5xx/panic/service death = Type3)."""
    label = f"shard_number={value} (spec-legal, resource strain)"
    name = new_name("r")
    # caller drops this name right after the leg (large-shard collections are heavy)
    st, raw = create(name, {"vectors": {"size": DIM, "distance": "Cosine"},
                            "shard_number": value}, timeout=http_timeout)
    print(f"[{label}] status={st} raw={str(raw)[:300]}")
    if not transport_gate(label, st, raw, findings):
        return name
    if 200 <= st <= 299:
        # completed branch: persisted shard count must equal the requested count
        if not envelope_result_true(raw):
            findings.append((2, f"Type4_StateLogicViolation: '{label}' 200 but envelope "
                                f"violates result:boolean=true grid; raw: {str(raw)[:200]}"))
            return name
        res, err = describe_result(name)
        got = walk(res, ["config", "params", "shard_number"]) if isinstance(res, dict) else None
        if got == value:
            print(f"[conform*] '{label}' completed with {st}; readback shard_number={got!r}")
        elif got is None:
            print(f"[observe-only] '{label}' completed with {st} but describe unavailable "
                  f"({err or ''}) - completion itself satisfies the constraint; readback "
                  f"not adjudicated")
        else:
            findings.append((2, f"Type4_StateLogicViolation: '{label}' 200 but readback "
                                f"config.params.shard_number={got!r} != sent {value}"))
    elif 400 <= st <= 499 and st != 404:
        print(f"[conform] '{label}' rejected with {st} (constraint's 'rejected with an error' "
              f"branch); body naming check (Type-2, observe-only): "
              f"{'shard' in str(raw).lower()}")
    else:
        findings.append((3, f"SCRIPT-ERROR: '{label}' unexpected status {st}; raw: {str(raw)[:150]}"))
    return name


def drop_now(name, timeout=120):
    try:
        safe_request("DELETE", "drop_collection", path_params={"name": name},
                     timeout=timeout)
    except Exception as e:
        print(f"cleanup warning (drop {name}): {e}")


def main():
    print(f"ownership prefix: {PFX}")
    print(f"[constraint quote] {ASSERT}")
    findings = []
    try:
        below_min_leg(0, findings)
        below_min_leg(-1, findings)
        min_closure_leg(findings)
        drop_now(resource_leg(1000, 120, findings))
        drop_now(resource_leg(100000, 120, findings))
        drop_now(resource_leg(4294967295, 150, findings))

        if findings:
            findings.sort(key=lambda x: x[0])
            rank, msg = findings[0]
            if rank == 3:
                print(f"VERDICT: SCRIPT_ERROR - {msg}")
                sys.exit(2)
            print(f"VERDICT: DEFECT_FOUND ({msg})")
            sys.exit(1)
        print("OK: below-min 0/-1 rejected; min=1 closure persisted; spec-legal large "
              "shard_number values completed or rejected without service death")
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
