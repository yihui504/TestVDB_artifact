#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_create_006
# strategy: type_boundary (strategy 2)
# endpoint: collections+create
# constraint_ids: qdrant_type_collections_create_006
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 Parameter Type Coercion Trust (new-in-1.18 memory enum: an
#   unsupported placement for dense storage silently accepted)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-boundary x qdrant_type_collections_create_006 on collections+create
  (PUT /collections/{collection_name}; chunk_collections+create-1of2 unit
  constraints::qdrant_type_collections_create_006, evidence_tier=explicit). The
  constraint's assertion, quoted verbatim:
    "memory IN {cold, cached, pinned}; pinned is not supported for dense vector storage"
  (memory replaces the deprecated on_disk/always_ram booleans in 1.18). Legs (G4 both
  directions, fresh collection per leg, Pattern B' judge_schema_attack):
    negative: vectors.memory="hot" (not in the enum);
      vectors.memory="pinned" (enum member explicitly unsupported for dense vector
      storage - the spec description says "pinned is not supported for dense vector
      storage");
    positive closure: vectors.memory="cached" -> 200 with describe readback
      result.config.params.vectors.memory=="cached".
  Readback caveat (declared): describe resolves memory to a default ("cached") when the
  field is dropped, so 200-on-illegal readbacks are refined by printed value comparison
  (persisted==sent -> Type1; otherwise Type2-signal, drop-with-default indistinguishable,
  judge adjudicates).
[chunk_collections+create-1of2 coverage: strategy2 x qdrant_type_collections_create_006
  (this script); siblings 001..005 cover type_001.._005; 007..012 cover strategy1 x
  range_001.._006]
Oracle: memory="hot" -> 4xx (200 + persisted "hot" = Type1); memory="pinned" (dense) ->
  4xx per the dense-only restriction (200 + persisted "pinned" = Type1; coerced
  "cached" = Type2-signal, judge adjudicates); positive "cached" -> 200
  result:true(boolean envelope) + readback vectors.memory=="cached" (other readback =
  Type4); legal placement rejected 4xx = Type4 disposition conflict; 5xx with /healthz
  alive or dead-after-3-probes = Type3; transport failure with healthy /healthz =
  SCRIPT_ERROR.
Constraint: qdrant_type_collections_create_006
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
doc_version: 1.18.x (versioned v-1-18-x api-reference)

R8-lesson spec-grid cross-check (BEFORE oracle): the versioned v-1-18-x merged OpenAPI
declares Memory enum ["cold","cached","pinned"] with VectorParams.memory =
oneOf[Memory, Any] and the description "pinned is not supported for dense vector
storage. Default: cached" - the contract grid IS corroborated by the published spec
(enum + dense-only restriction both present). The oneOf "Any type" wrapper makes silent
leniency plausible; the readback refinement distinguishes.
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

PFX = "bcc06" + uuid.uuid4().hex[:6]
CREATED = []
DIM = 4
DENSE = {"size": DIM, "distance": "Cosine"}
ASSERT = "memory IN {cold, cached, pinned}; pinned is not supported for dense vector storage"


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
    v = rt.judge_schema_attack(st, raw, name, ["config", "params", "vectors", "memory"],
                               attack_value, setup_ok=True)
    if v == "DEFECT_FOUND":
        res, err = describe_result(name)
        persisted = walk(res, ["config", "params", "vectors", "memory"]) \
            if isinstance(res, dict) else None
        if persisted == attack_value:
            kind = "Type1_IllegalSuccess (persisted as-is)"
        else:
            kind = ("Type2-signal (readback differs from sent - silent normalize or "
                    "drop-with-default; judge to adjudicate)")
        findings.append((0, f"{kind}: '{label}' accepted with {st}; sent={attack_value!r} "
                            f"persisted={persisted!r}; assertion: {ASSERT}"))
    elif v == "NO_DEFECT":
        if st in (200, 201):
            print(f"[conform*] '{label}' 200 but memory dropped/defaulted (lenient path)")
        else:
            print(f"[conform] '{label}' rejected with {st}")
    else:
        findings.append((3, f"SCRIPT-ERROR: '{label}' judge={v} status={st} raw={str(raw)[:150]}"))


def main():
    print(f"ownership prefix: {PFX}")
    print(f"[constraint quote] {ASSERT}")
    findings = []
    try:
        value_leg("vectors.memory='hot' (not in enum)",
                  {"vectors": {"size": DIM, "distance": "Cosine", "memory": "hot"}},
                  "hot", findings)
        value_leg("vectors.memory='pinned' (dense storage unsupported)",
                  {"vectors": {"size": DIM, "distance": "Cosine", "memory": "pinned"}},
                  "pinned", findings)

        # positive closure: cached persisted
        name = PFX + "p0"
        CREATED.append(name)
        st, raw = create(name, {"vectors": {"size": DIM, "distance": "Cosine",
                                            "memory": "cached"}})
        print(f"[positive memory='cached' closure] status={st} raw={str(raw)[:300]}")
        if transport_gate("positive memory cached closure", st, raw, findings):
            v = rt.judge_200(st, raw, setup_ok=True)
            if v == "DEFECT_FOUND":
                findings.append((2, f"Type4 disposition conflict: documented-legal placement "
                                    f"'cached' rejected with {st}; raw: {str(raw)[:200]}"))
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
                    got = walk(res, ["config", "params", "vectors", "memory"]) \
                        if isinstance(res, dict) else None
                    if got == "cached":
                        print("[conform] memory cached closure persisted in readback")
                    else:
                        findings.append((2, f"Type4_StateLogicViolation: memory cached accepted "
                                            f"but readback vectors.memory={got!r} != 'cached'"))

        if findings:
            findings.sort(key=lambda x: x[0])
            rank, msg = findings[0]
            if rank == 3:
                print(f"VERDICT: SCRIPT_ERROR - {msg}")
                sys.exit(2)
            print(f"VERDICT: DEFECT_FOUND ({msg})")
            sys.exit(1)
        print("OK: memory enum enforced; pinned rejected for dense; cached persisted")
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
