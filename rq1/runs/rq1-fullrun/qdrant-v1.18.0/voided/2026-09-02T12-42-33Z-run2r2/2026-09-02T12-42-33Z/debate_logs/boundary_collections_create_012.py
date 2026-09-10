#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_create_012
# strategy: boundary (strategy 1)
# endpoint: collections+create
# constraint_ids: qdrant_range_collections_create_006
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 Boundary Default Optimism (a deprecated-but-present guardrail whose
#   [1,100] window is no longer validated)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary-value x qdrant_range_collections_create_006 on collections+create
  (PUT /collections/{collection_name}; chunk_collections+create-1of2 unit
  constraints::qdrant_range_collections_create_006, evidence_tier=explicit). The
  constraint's assertion, quoted verbatim:
    "strict_mode_config.max_resident_memory_percent within [1, 100] when set (deprecated
     in 1.18)"
  The field is deprecated in 1.18 (removal scheduled 1.21, superseded by PUT /quotas)
  but still documented in the v1.18 spec with minimum 1 / maximum 100 - validation must
  still hold while it exists. Legs (G4 both directions, fresh collection per leg,
  Pattern B' judge_schema_attack for the negatives):
    negative: strict_mode_config.max_resident_memory_percent=0 (min-1), =101 (max+1);
    positive closures: =1 -> 200 + readback
      result.config.strict_mode_config.max_resident_memory_percent==1; =100 -> 200 +
      readback ==100 (both closed endpoints accepted).
[chunk_collections+create-1of2 coverage: strategy1 x qdrant_range_collections_create_006
  (this script); siblings 007..011 cover range_001.._005; 001..006 cover strategy2 x
  type_001.._006]
Oracle: 0 and 101 -> 4xx each (200 + persisted-as-sent = Type1_IllegalSuccess; coerced
  in-range value = Type2-signal, judge adjudicates); 1 and 100 -> 200
  result:true(boolean) + readback ==sent (other readback = Type4; closed endpoint
  rejected 4xx = Type4 disposition conflict); 5xx with /healthz alive or
  dead-after-3-probes = Type3; transport failure with healthy /healthz = SCRIPT_ERROR.
Constraint: qdrant_range_collections_create_006
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
doc_version: 1.18.x (versioned v-1-18-x api-reference)

R8-lesson spec-grid cross-check (BEFORE oracle): the versioned v-1-18-x merged OpenAPI
StrictModeConfig declares max_resident_memory_percent {integer, minimum: 1, maximum:
100, deprecated: true} and CreateCollectionStrictModeConfig = oneOf[StrictModeConfig,
Any type] - the contract grid IS corroborated by the published schema (bounds present,
deprecation present). The oneOf "Any type" wrapper makes silent leniency plausible;
the readback refinement (result.config.strict_mode_config.max_resident_memory_percent)
distinguishes persist vs coerce vs drop.
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

PFX = "bcc12" + uuid.uuid4().hex[:6]
CREATED = []
DIM = 4
DENSE = {"size": DIM, "distance": "Cosine"}
ASSERT = "strict_mode_config.max_resident_memory_percent within [1, 100] when set (deprecated in 1.18)"
SPATH = ["config", "strict_mode_config", "max_resident_memory_percent"]


def safe_request(method, path_key, **kw):
    return rt.request(method, path_key, **kw)


def healthz_ladder(label, attempts=3, delay=2):
    for i in range(attempts):
        hs, hraw = safe_request("GET", "healthz")
        print(f"[healthz attempt {i + 1}] status={hs} raw={str(hraw)[:120]}")
        if 200 <= hs < 300:
            return None
        if i < attempts - 1:
            time.sleep(delay)
    return (f"Type3_RuntimeFailure(service-down) - '{label}': /healthz unreachable "
            f"after {attempts} attempts")


def create(name, body):
    return safe_request("PUT", "create_collection", body=body,
                        path_params={"name": name}, timeout=60)


def describe_result(name):
    st, raw = safe_request("GET", "describe_collection",
                           path_params={"name": name}, timeout=30)
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


def transport_gate(label, st, raw, findings):
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


def main():
    print(f"ownership prefix: {PFX}")
    print(f"[constraint quote] {ASSERT}")
    findings = []
    legs = [
        ("max_resident_memory_percent=0 (min-1)", 0, "4xx"),
        ("max_resident_memory_percent=101 (max+1)", 101, "4xx"),
        ("max_resident_memory_percent=1 (closed lower endpoint)", 1, "2xx"),
        ("max_resident_memory_percent=100 (closed upper endpoint)", 100, "2xx"),
    ]
    try:
        for label, val, expected in legs:
            name = PFX + "l" + str(len(CREATED))
            CREATED.append(name)
            body = {"vectors": DENSE,
                    "strict_mode_config": {"max_resident_memory_percent": val}}
            st, raw = create(name, body)
            print(f"[{label}] status={st} raw={str(raw)[:300]}")
            if not transport_gate(label, st, raw, findings):
                break
            if expected == "4xx":
                v = rt.judge_schema_attack(st, raw, name, SPATH, val, setup_ok=True)
                if v == "DEFECT_FOUND":
                    res, err = describe_result(name)
                    persisted = walk(res, SPATH) if isinstance(res, dict) else None
                    if persisted == val:
                        kind = "Type1_IllegalSuccess (persisted as-is)"
                    else:
                        kind = ("Type2-signal (readback differs from sent - silent clamp; "
                                "judge to adjudicate)")
                    findings.append((0, f"{kind}: '{label}' accepted with {st}; sent={val!r} "
                                        f"persisted={persisted!r}; assertion: {ASSERT}"))
                elif v == "NO_DEFECT":
                    if st in (200, 201):
                        print(f"[conform*] '{label}' 200 but strict field dropped (lenient path)")
                    else:
                        print(f"[conform] '{label}' rejected with {st}")
                else:
                    findings.append((3, f"SCRIPT-ERROR: '{label}' judge={v} status={st}"))
            else:
                v = rt.judge_200(st, raw, setup_ok=True)
                if v == "DEFECT_FOUND":
                    findings.append((2, f"Type4 disposition conflict: closed-endpoint value "
                                        f"{val} rejected with {st}; raw: {str(raw)[:200]}"))
                    continue
                try:
                    env = json.loads(raw) if raw else {}
                    ok_env = isinstance(env.get("result"), bool) and env["result"]
                except Exception:
                    ok_env = False
                if not ok_env:
                    findings.append((2, f"Type4_StateLogicViolation: '{label}' 2xx but envelope "
                                        f"violates result:boolean=true grid; raw: {str(raw)[:200]}"))
                    continue
                res, err = describe_result(name)
                got = walk(res, SPATH) if isinstance(res, dict) else None
                smc = walk(res, ["config", "strict_mode_config"]) if isinstance(res, dict) else None
                print(f"[readback] config.strict_mode_config={json.dumps(smc)[:250]}")
                if got == val:
                    print(f"[conform] '{label}' 200; readback {got!r} persisted (closure)")
                else:
                    findings.append((2, f"Type4_StateLogicViolation: '{label}' accepted but "
                                        f"readback max_resident_memory_percent={got!r} != {val!r}"))

        if findings:
            findings.sort(key=lambda x: x[0])
            rank, msg = findings[0]
            if rank == 3:
                print(f"VERDICT: SCRIPT_ERROR - {msg}")
                sys.exit(2)
            print(f"VERDICT: DEFECT_FOUND ({msg})")
            sys.exit(1)
        print("OK: out-of-window values rejected/clamped-noted; both closed endpoints persisted")
        print("VERDICT: NO_DEFECT")
        sys.exit(0)
    finally:
        for n in list(CREATED):
            try:
                rt.drop_collection(n)
            except Exception as e:
                print(f"cleanup warning (drop {n}): {e}")


if __name__ == "__main__":
    main()
