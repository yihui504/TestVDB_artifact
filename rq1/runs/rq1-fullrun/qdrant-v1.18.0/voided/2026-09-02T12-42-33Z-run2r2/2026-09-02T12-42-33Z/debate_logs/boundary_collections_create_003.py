#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_create_003
# strategy: type_boundary (strategy 2)
# endpoint: collections+create
# constraint_ids: qdrant_type_collections_create_003
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 Parameter Type Coercion Trust (out-of-enum / wrong-case enum values
#   silently coerced instead of rejected)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-boundary x qdrant_type_collections_create_003 on collections+create
  (PUT /collections/{collection_name}; chunk_collections+create-1of2 unit
  constraints::qdrant_type_collections_create_003, evidence_tier=explicit). The
  constraint's assertion, quoted verbatim:
    "sharding_method IN {auto, custom} (versioned spec ShardingMethod enum; wire values
     are lowercase snake_case)"
  - and the constraint description names the concept-doc prose variant 'hash_slot' as
  NOT part of the v1.18.0 spec. Legs (G4 both directions, fresh collection per leg):
    negative (Pattern B' judge_schema_attack): sharding_method="hash_slot" (out-of-enum
      prose variant), sharding_method="Auto" (wrong case - enum wires lowercase);
    positive closures: sharding_method="auto" -> 200 + describe readback
      result.config.params.sharding_method=="auto"; sharding_method="custom" -> 200 +
      readback "custom" (full enum closure, both members).
[chunk_collections+create-1of2 coverage: strategy2 x qdrant_type_collections_create_003
  (this script); siblings 001/002/004..006 cover type_001/_002/_004.._006; 007..012
  cover strategy1 x range_001.._006]
Oracle: "hash_slot" and "Auto" -> 4xx each (200 + persisted-as-sent = Type1 enum
  violation; 200 + coerced to a legal member = Type2-signal, drop-with-default
  indistinguishable on this face, judge adjudicates); positive legs -> 200 with
  result:true(boolean envelope) and readback sharding_method exactly "auto" / "custom"
  (any other readback on a hard leg = Type4); legal enum member rejected 4xx = Type4
  disposition conflict; 5xx with /healthz alive or dead-after-3-probes = Type3;
  transport failure with healthy /healthz = SCRIPT_ERROR.
Constraint: qdrant_type_collections_create_003
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
doc_version: 1.18.x (versioned v-1-18-x api-reference)

R8-lesson spec-grid cross-check (BEFORE oracle): the versioned v-1-18-x merged OpenAPI
declares ShardingMethod enum ["auto","custom"] (snake_case wire values) and
CreateCollectionShardingMethod = oneOf[ShardingMethod, Any] - the contract grid IS
corroborated by the published enum. The oneOf "Any type" wrapper makes silent
leniency plausible, which is precisely what the readback refinement distinguishes.
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

PFX = "bcc03" + uuid.uuid4().hex[:6]
CREATED = []
DIM = 4
DENSE = {"size": DIM, "distance": "Cosine"}
ASSERT = "sharding_method IN {auto, custom} (versioned spec ShardingMethod enum; wire values are lowercase snake_case)"


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


def value_leg(label, body, attack_value, findings):
    name = PFX + "n" + str(len(CREATED))
    CREATED.append(name)
    st, raw = create(name, body)
    print(f"[{label}] status={st} raw={str(raw)[:300]}")
    if not transport_gate(label, st, raw, findings):
        return
    v = rt.judge_schema_attack(st, raw, name, ["config", "params", "sharding_method"],
                               attack_value, setup_ok=True)
    if v == "DEFECT_FOUND":
        res, err = describe_result(name)
        persisted = walk(res, ["config", "params", "sharding_method"]) if isinstance(res, dict) else None
        if persisted == attack_value:
            kind = "Type1_IllegalSuccess (persisted as-is)"
        else:
            kind = ("Type2-signal (readback differs from sent - silent coercion to a legal "
                    "member or drop; judge to adjudicate against the strict enum)")
        findings.append((0, f"{kind}: '{label}' accepted with {st}; sent={attack_value!r} "
                            f"persisted={persisted!r}; assertion: {ASSERT}"))
    elif v == "NO_DEFECT":
        if st in (200, 201):
            print(f"[conform*] '{label}' 200 but sharding_method dropped from resolved config (lenient path)")
        else:
            print(f"[conform] '{label}' rejected with {st}")
    else:
        findings.append((3, f"SCRIPT-ERROR: '{label}' judge={v} status={st} raw={str(raw)[:150]}"))


def positive_leg(label, sharding, findings):
    name = PFX + "p" + str(len(CREATED))
    CREATED.append(name)
    st, raw = create(name, {"vectors": DENSE, "sharding_method": sharding})
    print(f"[{label}] status={st} raw={str(raw)[:300]}")
    if not transport_gate(label, st, raw, findings):
        return
    v = rt.judge_200(st, raw, setup_ok=True)
    if v == "DEFECT_FOUND":
        findings.append((2, f"Type4 disposition conflict: documented-legal enum member "
                            f"{sharding!r} rejected with {st}; raw: {str(raw)[:200]}"))
        return
    try:
        env = json.loads(raw) if raw else {}
        ok_env = isinstance(env.get("result"), bool) and env["result"]
    except Exception:
        ok_env = False
    if not ok_env:
        findings.append((2, f"Type4_StateLogicViolation: '{label}' 200 but envelope violates "
                            f"result:boolean=true grid; raw: {str(raw)[:200]}"))
        return
    res, err = describe_result(name)
    got = walk(res, ["config", "params", "sharding_method"]) if isinstance(res, dict) else None
    if got == sharding:
        print(f"[conform] '{label}' 200; readback sharding_method={got!r}")
    elif got is None:
        print(f"[observe-only] '{label}' 200 but resolved config omits sharding_method "
              f"(default-auto omission is spec-possible; sent {sharding!r}) - measured")
    else:
        findings.append((2, f"Type4_StateLogicViolation: '{label}' accepted but readback "
                            f"sharding_method={got!r} != sent {sharding!r}"))


def main():
    print(f"ownership prefix: {PFX}")
    print(f"[constraint quote] {ASSERT}")
    findings = []
    try:
        value_leg("sharding_method='hash_slot' (prose variant, not in v1.18 spec)",
                  {"vectors": DENSE, "sharding_method": "hash_slot"}, "hash_slot", findings)
        value_leg("sharding_method='Auto' (wrong case)",
                  {"vectors": DENSE, "sharding_method": "Auto"}, "Auto", findings)
        positive_leg("sharding_method='auto' (closure)", "auto", findings)
        positive_leg("sharding_method='custom' (closure)", "custom", findings)

        if findings:
            findings.sort(key=lambda x: x[0])
            rank, msg = findings[0]
            if rank == 3:
                print(f"VERDICT: SCRIPT_ERROR - {msg}")
                sys.exit(2)
            print(f"VERDICT: DEFECT_FOUND ({msg})")
            sys.exit(1)
        print("OK: out-of-enum values rejected/dropped; both enum members accepted+persisted")
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
