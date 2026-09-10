#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_create_004
# strategy: type_boundary (strategy 2)
# endpoint: collections+create
# constraint_ids: qdrant_type_collections_create_004
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 Parameter Type Coercion Trust (nested quantization enums trusted to
#   serde; out-of-enum compression/encoding slipping through)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-boundary x qdrant_type_collections_create_004 on collections+create
  (PUT /collections/{collection_name}; chunk_collections+create-1of2 unit
  constraints::qdrant_type_collections_create_004, evidence_tier=explicit). The
  constraint's assertion, quoted verbatim:
    "quantization_config type domain: ScalarQuantization.type = int8;
     ProductQuantization.compression IN {x4, x8, x16, x32, x64};
     BinaryQuantization.encoding IN {one_bit, two_bits, one_and_half_bits}"
  Legs (G4 both directions, fresh collection per leg, all Pattern B'
  judge_schema_attack for the illegal values):
    negative: quantization_config.scalar.type="int16" (ScalarType enum is [int8] only);
      quantization_config.product.compression="x2" (not in the x4..x64 ladder);
      quantization_config.binary.encoding="three_bits" (not in the encoding enum);
    positive closures: quantization_config=null -> 200 (constraint description: "null
      disables quantization"; readback must show NO active quantization), and
      quantization_config={"scalar":{"type":"int8"}} -> 200 with readback
      result.config.quantization_config.scalar.type=="int8" (enum closure).
[chunk_collections+create-1of2 coverage: strategy2 x qdrant_type_collections_create_004
  (this script); siblings 001..003/005/006 cover type_001.._003/_005/_006; 007..012
  cover strategy1 x range_001.._006]
Oracle: each illegal enum value -> 4xx (200 + persisted-as-sent = Type1; 200 + coerced
  legal value = Type2-signal, drop indistinguishable on this face, judge adjudicates);
  null-disable leg -> 200 result:true(boolean) and describe quantization_config
  falsy/absent (an ACTIVE quantization after null = Type4_StateLogicViolation);
  scalar int8 closure -> 200 + readback scalar.type=="int8" (mismatch = Type4);
  legal form rejected 4xx = Type4 disposition conflict; 5xx with /healthz alive or
  dead-after-3-probes = Type3; transport failure with healthy /healthz = SCRIPT_ERROR.
Constraint: qdrant_type_collections_create_004
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
doc_version: 1.18.x (versioned v-1-18-x api-reference)

R8-lesson spec-grid cross-check (BEFORE oracle): the versioned v-1-18-x merged OpenAPI
declares ScalarType enum ["int8"], CompressionRatio enum ["x4","x8","x16","x32","x64"],
BinaryQuantizationEncoding enum ["one_bit","two_bits","one_and_half_bits"],
ScalarQuantization required=[type], ProductQuantization required=[compression] - the
contract grid IS corroborated member-for-member. QuantizationConfig oneOf
[scalar|product|binary|turbo] single-key forms (raw_knowledge request_required_paths
agree: quantization_config.scalar.type etc. are branch-required).
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

PFX = "bcc04" + uuid.uuid4().hex[:6]
CREATED = []
DIM = 4
DENSE = {"size": DIM, "distance": "Cosine"}
ASSERT = ("quantization_config type domain: ScalarQuantization.type = int8; "
          "ProductQuantization.compression IN {x4, x8, x16, x32, x64}; "
          "BinaryQuantization.encoding IN {one_bit, two_bits, one_and_half_bits}")


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


def value_leg(label, body, attack_path, attack_value, findings):
    name = PFX + "n" + str(len(CREATED))
    CREATED.append(name)
    st, raw = create(name, body)
    print(f"[{label}] status={st} raw={str(raw)[:300]}")
    if not transport_gate(label, st, raw, findings):
        return
    v = rt.judge_schema_attack(st, raw, name, attack_path, attack_value, setup_ok=True)
    if v == "DEFECT_FOUND":
        res, err = describe_result(name)
        persisted = walk(res, attack_path) if isinstance(res, dict) else None
        if persisted == attack_value:
            kind = "Type1_IllegalSuccess (persisted as-is)"
        else:
            kind = ("Type2-signal (readback differs from sent - silent normalize or "
                    "drop-with-default; judge to adjudicate)")
        findings.append((0, f"{kind}: '{label}' accepted with {st}; sent={attack_value!r} "
                            f"persisted={persisted!r}; assertion: {ASSERT}"))
    elif v == "NO_DEFECT":
        if st in (200, 201):
            print(f"[conform*] '{label}' 200 but quantization branch dropped (lenient path)")
        else:
            print(f"[conform] '{label}' rejected with {st}")
    else:
        findings.append((3, f"SCRIPT-ERROR: '{label}' judge={v} status={st} raw={str(raw)[:150]}"))


def main():
    print(f"ownership prefix: {PFX}")
    print(f"[constraint quote] {ASSERT}")
    findings = []
    try:
        value_leg("quantization scalar.type='int16' (enum is [int8])",
                  {"vectors": DENSE, "quantization_config": {"scalar": {"type": "int16"}}},
                  ["config", "quantization_config", "scalar", "type"], "int16", findings)
        value_leg("quantization product.compression='x2' (not in x4..x64)",
                  {"vectors": DENSE, "quantization_config": {"product": {"compression": "x2"}}},
                  ["config", "quantization_config", "product", "compression"], "x2", findings)
        value_leg("quantization binary.encoding='three_bits' (not in enum)",
                  {"vectors": DENSE, "quantization_config": {"binary": {"encoding": "three_bits"}}},
                  ["config", "quantization_config", "binary", "encoding"], "three_bits", findings)

        # positive closure 1: null disables quantization (documented)
        name = PFX + "p0"
        CREATED.append(name)
        st, raw = create(name, {"vectors": DENSE, "quantization_config": None})
        print(f"[positive null-disable closure] status={st} raw={str(raw)[:300]}")
        if transport_gate("positive null-disable closure", st, raw, findings):
            v = rt.judge_200(st, raw, setup_ok=True)
            if v == "DEFECT_FOUND":
                findings.append((2, f"Type4 disposition conflict: documented null-disable "
                                    f"form rejected with {st}; raw: {str(raw)[:200]}"))
            else:
                try:
                    env = json.loads(raw) if raw else {}
                    ok_env = isinstance(env.get("result"), bool) and env["result"]
                except Exception:
                    ok_env = False
                if not ok_env:
                    findings.append((2, f"Type4_StateLogicViolation: 200 but envelope violates "
                                        f"result:boolean=true grid; raw: {str(raw)[:200]}"))
                else:
                    res, err = describe_result(name)
                    q = walk(res, ["config", "quantization_config"]) if isinstance(res, dict) else None
                    if not q:
                        print("[conform] null-disable closure: no active quantization in readback")
                    else:
                        findings.append((2, f"Type4_StateLogicViolation: quantization_config=null "
                                            f"accepted but readback shows ACTIVE quantization: "
                                            f"{json.dumps(q)[:200]} (promise: null disables)"))

        # positive closure 2: scalar int8 enum closure, persisted
        name = PFX + "p1"
        CREATED.append(name)
        st, raw = create(name, {"vectors": DENSE,
                                "quantization_config": {"scalar": {"type": "int8"}}})
        print(f"[positive scalar int8 closure] status={st} raw={str(raw)[:300]}")
        if transport_gate("positive scalar int8 closure", st, raw, findings):
            v = rt.judge_200(st, raw, setup_ok=True)
            if v == "DEFECT_FOUND":
                findings.append((2, f"Type4 disposition conflict: documented scalar int8 form "
                                    f"rejected with {st}; raw: {str(raw)[:200]}"))
            else:
                res, err = describe_result(name)
                got = walk(res, ["config", "quantization_config", "scalar", "type"]) \
                    if isinstance(res, dict) else None
                if got == "int8":
                    print("[conform] scalar int8 closure persisted in readback")
                else:
                    findings.append((2, f"Type4_StateLogicViolation: scalar int8 accepted but "
                                        f"readback scalar.type={got!r} != 'int8'"))

        if findings:
            findings.sort(key=lambda x: x[0])
            rank, msg = findings[0]
            if rank == 3:
                print(f"VERDICT: SCRIPT_ERROR - {msg}")
                sys.exit(2)
            print(f"VERDICT: DEFECT_FOUND ({msg})")
            sys.exit(1)
        print("OK: quantization enums enforced; null disables; int8 closure persisted")
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
