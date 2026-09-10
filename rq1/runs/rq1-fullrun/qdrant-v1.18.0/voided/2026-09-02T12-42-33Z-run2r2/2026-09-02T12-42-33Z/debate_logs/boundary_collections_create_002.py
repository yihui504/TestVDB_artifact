#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_create_002
# strategy: type_boundary (strategy 2)
# endpoint: collections+create
# constraint_ids: qdrant_type_collections_create_002
# source_url: https://qdrant.tech/documentation/manage-data/vectors/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-01 Parameter Type Coercion Trust (map-typed config fed an array;
#   a non-settable field fed a value and silently kept it)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-boundary x qdrant_type_collections_create_002 on collections+create
  (PUT /collections/{collection_name}; chunk_collections+create-1of2 unit
  constraints::qdrant_type_collections_create_002, evidence_tier=explicit). The
  constraint's assertion, quoted verbatim:
    "sparse vector distance IS Dot (not user-settable); sparse_vectors configuration
     is a map of vector-name to SparseVectorParams"
  Legs (G4 both directions, fresh collection per leg):
    negative (Pattern B' judge_schema_attack): sparse_vectors=[] (array fed to a
      map-typed field - type confusion); sparse_vectors={"sp": {"distance":"Cosine"}}
      (distance is documented NOT user-settable for sparse vectors - persisting any
      value there violates the assertion);
    positive closure: sparse_vectors={"sp": {}} + valid dense vectors -> 200 with
      envelope result:boolean=true and describe readback
      result.config.params.sparse_vectors["sp"] present as an object.
  Observability note (spec-verified): the describe-side SparseVectorConfig grid
  carries {modifier, datatype} and NO distance key - "always Dot" is not observable
  on this face; the observable promise is map-shape acceptance with no distance input
  and no persistence of a user-supplied distance.
[chunk_collections+create-1of2 coverage: strategy2 x qdrant_type_collections_create_002
  (this script); siblings 001/003..006 cover type_001/_003.._006; 007..012 cover
  strategy1 x range_001.._006]
Oracle: sparse_vectors=[] -> 4xx (map type violated; 200 = Type1 candidate);
  sparse distance="Cosine" -> 4xx or silent-drop (either is conform: drop is the
  documented-lenient path); 200 + describe sparse_vectors.sp.distance=="Cosine"
  persisted = Type1_IllegalSuccess (distance not user-settable); positive leg -> 200
  result:true(boolean) + sparse_vectors["sp"] object present (missing key = Type4);
  legal map rejected 4xx = Type4 disposition conflict; 5xx with /healthz alive or
  dead-after-3-probes = Type3; transport failure with healthy /healthz = SCRIPT_ERROR.
Constraint: qdrant_type_collections_create_002
source_url: https://qdrant.tech/documentation/manage-data/vectors/
doc_version: current (site latest; no version archive)

R8-lesson spec-grid cross-check (BEFORE oracle): the versioned v-1-18-x merged
OpenAPI declares sparse_vectors {object|null, additionalProperties: SparseVectorParams}
and SparseVectorParams properties = {index, modifier} only (no distance); the
describe-side SparseVectorConfig = {modifier, datatype} (no distance key). The
contract's "map of name -> SparseVectorParams" is corroborated; "distance always Dot,
not user-settable" is description-level (vectors doc) - readback can only detect a
persisted violation, never confirm Dot (annotated honestly above).
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

PFX = "bcc02" + uuid.uuid4().hex[:6]
CREATED = []
DIM = 4
DENSE = {"size": DIM, "distance": "Cosine"}
ASSERT = ("sparse vector distance IS Dot (not user-settable); sparse_vectors "
          "configuration is a map of vector-name to SparseVectorParams")


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
            print(f"[conform*] '{label}' 200 but attacked field silent-dropped (lenient path)")
        else:
            print(f"[conform] '{label}' rejected with {st}")
    else:
        findings.append((3, f"SCRIPT-ERROR: '{label}' judge={v} status={st} raw={str(raw)[:150]}"))


def main():
    print(f"ownership prefix: {PFX}")
    print(f"[constraint quote] {ASSERT}")
    findings = []
    try:
        value_leg("sparse_vectors=[] (array for map-typed field)",
                  {"vectors": DENSE, "sparse_vectors": []},
                  ["config", "params", "sparse_vectors"], [], findings)
        value_leg("sparse_vectors={'sp':{'distance':'Cosine'}} (distance not user-settable)",
                  {"vectors": DENSE, "sparse_vectors": {"sp": {"distance": "Cosine"}}},
                  ["config", "params", "sparse_vectors", "sp", "distance"], "Cosine", findings)

        # positive closure: map-shape accepted, named sparse vector configured
        name = PFX + "p0"
        CREATED.append(name)
        st, raw = create(name, {"vectors": DENSE, "sparse_vectors": {"sp": {}}})
        print(f"[positive sparse map closure] status={st} raw={str(raw)[:300]}")
        if transport_gate("positive sparse map closure", st, raw, findings):
            v = rt.judge_200(st, raw, setup_ok=True)
            if v == "DEFECT_FOUND":
                findings.append((2, f"Type4 disposition conflict: documented map form "
                                    f"sparse_vectors={{'sp':{{}}}} rejected with {st}; raw: {str(raw)[:200]}"))
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
                    sp = walk(res, ["config", "params", "sparse_vectors", "sp"]) \
                        if isinstance(res, dict) else None
                    if isinstance(sp, dict):
                        print(f"[conform] positive closure: sparse_vectors['sp'] present in "
                              f"describe readback: {json.dumps(sp)[:200]}")
                    else:
                        findings.append((2, f"Type4_StateLogicViolation: 200 accepted but describe "
                                            f"readback lacks sparse_vectors['sp'] (err={err}); "
                                            f"the configured sparse vector did not materialize"))

        if findings:
            findings.sort(key=lambda x: x[0])
            rank, msg = findings[0]
            if rank == 3:
                print(f"VERDICT: SCRIPT_ERROR - {msg}")
                sys.exit(2)
            print(f"VERDICT: DEFECT_FOUND ({msg})")
            sys.exit(1)
        print("OK: map type enforced (or dropped); non-settable distance not persisted; map closure materialized")
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
