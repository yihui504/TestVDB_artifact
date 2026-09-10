#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_create_010
# strategy: boundary (strategy 1)
# endpoint: collections+create
# constraint_ids: qdrant_range_collections_create_004
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 Boundary Default Optimism (optimizer knobs below their documented
#   minima silently accepted)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary-value x qdrant_range_collections_create_004 on collections+create
  (PUT /collections/{collection_name}; chunk_collections+create-1of2 unit
  constraints::qdrant_range_collections_create_004, evidence_tier=explicit). The
  constraint's assertion, quoted verbatim:
    "optimizers_config bounds: deleted_threshold within [0, 1]; vacuum_min_vector_number
     minimum 100; max_segment_size minimum 1 KB; memmap_threshold minimum 0;
     indexing_threshold minimum 0 KB"
  Legs (G4 both directions, fresh collection per leg):
    HARD negative (Pattern B' judge_schema_attack; both published grids agree min 0):
      optimizers_config.indexing_threshold=-1, optimizers_config.memmap_threshold=-1;
    HARD positive closures (documented disable semantics): indexing_threshold=0 -> 200 +
      readback result.config.optimizer_config.indexing_threshold==0; memmap_threshold=0
      -> 200 + readback ==0;
    CONFLICT-ZONE measured-only (R8/R9 lesson: spec grids disagree - the create-side
      OptimizersConfigDiff says vacuum_min_vector_number min 0 / max_segment_size min 0 /
      deleted_threshold unbounded, while the resolved describe-side OptimizersConfig
      grid carries min 100 / min 1 / [0,1] - the contract quotes the resolved grid):
      vacuum_min_vector_number=99, max_segment_size=0, deleted_threshold=1.5 ->
      disposition + readback PRINTED for the judge, NOT adjudicated (no defect claim on
      2xx/4xx either way; only 5xx counts as Type3).
  Describe readback key (spec-verified): result.config.optimizer_config (singular
  'optimizer' on the response side, vs optimizers_config in the request).
[chunk_collections+create-1of2 coverage: strategy1 x qdrant_range_collections_create_004
  (this script); siblings 007..009/011/012 cover range_001.._003/_005/_006; 001..006
  cover strategy2 x type_001.._006]
Oracle: indexing_threshold=-1 and memmap_threshold=-1 -> 4xx each (200 + persisted -1 =
  Type1_IllegalSuccess; coerced value = Type2-signal); the two 0-closures -> 200
  result:true(boolean) + readback ==0 (mismatch/missing = Type4; documented-legal 0
  rejected = Type4 disposition conflict); conflict-zone legs -> measured lines only
  (contribute NO defect unless 5xx, which with /healthz alive or dead-after-3-probes =
  Type3); transport failure with healthy /healthz = SCRIPT_ERROR.
Constraint: qdrant_range_collections_create_004
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
doc_version: 1.18.x (versioned v-1-18-x api-reference)

R8-lesson spec-grid cross-check (BEFORE oracle): the versioned v-1-18-x merged OpenAPI
OptimizersConfigDiff (create input) declares indexing_threshold {minimum: 0} and
memmap_threshold {minimum: 0} (0 = documented disable values) - corroborated. The same
file's resolved OptimizersConfig (describe output) carries vacuum_min_vector_number
{minimum: 100}, max_segment_size {minimum: 1}, deleted_threshold {minimum: 0, maximum: 1}
- corroborating the contract numbers but CONFLICTING with the input diff grid (vacuum
min 0 / max_segment 0 / deleted unbounded). Conflict fields -> measured-only per the
standing R8/R9 rule (spec wins on conflicts; conflict zones measured-only).
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

PFX = "bcc10" + uuid.uuid4().hex[:6]
CREATED = []
DIM = 4
DENSE = {"size": DIM, "distance": "Cosine"}
ASSERT = ("optimizers_config bounds: deleted_threshold within [0, 1]; vacuum_min_vector_number "
          "minimum 100; max_segment_size minimum 1 KB; memmap_threshold minimum 0; "
          "indexing_threshold minimum 0 KB")
OCFG = ["config", "optimizer_config"]  # describe-side key is singular 'optimizer_config'


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


def value_leg(label, body, field, attack_value, findings):
    path = OCFG + [field]
    name = PFX + "n" + str(len(CREATED))
    CREATED.append(name)
    st, raw = create(name, body)
    print(f"[{label}] status={st} raw={str(raw)[:300]}")
    if not transport_gate(label, st, raw, findings):
        return
    v = rt.judge_schema_attack(st, raw, name, path, attack_value, setup_ok=True)
    if v == "DEFECT_FOUND":
        res, err = describe_result(name)
        persisted = walk(res, path) if isinstance(res, dict) else None
        if persisted == attack_value:
            kind = "Type1_IllegalSuccess (persisted as-is)"
        else:
            kind = ("Type2-signal (readback differs from sent - silent clamp/normalize; "
                    "judge to adjudicate)")
        findings.append((0, f"{kind}: '{label}' accepted with {st}; sent={attack_value!r} "
                            f"persisted={persisted!r}; assertion: {ASSERT}"))
    elif v == "NO_DEFECT":
        if st in (200, 201):
            print(f"[conform*] '{label}' 200 but field dropped (lenient path)")
        else:
            print(f"[conform] '{label}' rejected with {st}")
    else:
        findings.append((3, f"SCRIPT-ERROR: '{label}' judge={v} status={st} raw={str(raw)[:150]}"))


def measured_leg(label, body, field, sent, findings):
    """R8/R9 conflict-zone leg: disposition + readback printed for the judge;
    NOT adjudicated (only 5xx counts, via transport_gate)."""
    name = PFX + "m" + str(len(CREATED))
    CREATED.append(name)
    st, raw = create(name, body)
    print(f"[measured-only:{label}] status={st} raw={str(raw)[:300]}")
    if not transport_gate(label, st, raw, findings):
        return
    res, err = describe_result(name) if st in (200, 201) else (None, "not-created")
    got = walk(res, OCFG + [field]) if isinstance(res, dict) else None
    print(f"[measured-only:{label}] input-grid(diff) vs resolved-grid disagree on this "
          f"bound; sent={sent!r} readback={got!r}; disposition={st}; "
          f"full optimizer_config={json.dumps(walk(res, OCFG) if isinstance(res, dict) else None)[:300]}")


def main():
    print(f"ownership prefix: {PFX}")
    print(f"[constraint quote] {ASSERT}")
    findings = []
    try:
        # HARD legs (both grids agree minimum 0)
        value_leg("optimizers_config.indexing_threshold=-1 (min-1, both grids)",
                  {"vectors": DENSE, "optimizers_config": {"indexing_threshold": -1}},
                  "indexing_threshold", -1, findings)
        value_leg("optimizers_config.memmap_threshold=-1 (min-1, both grids)",
                  {"vectors": DENSE, "optimizers_config": {"memmap_threshold": -1}},
                  "memmap_threshold", -1, findings)
        # HARD positive closures (documented disable semantics: 0)
        for field in ("indexing_threshold", "memmap_threshold"):
            name = PFX + "p" + str(len(CREATED))
            CREATED.append(name)
            st, raw = create(name, {"vectors": DENSE, "optimizers_config": {field: 0}})
            print(f"[positive {field}=0 closure (documented disable value)] status={st} raw={str(raw)[:300]}")
            if not transport_gate(f"positive {field}=0 closure", st, raw, findings):
                continue
            v = rt.judge_200(st, raw, setup_ok=True)
            if v == "DEFECT_FOUND":
                findings.append((2, f"Type4 disposition conflict: documented-legal {field}=0 "
                                    f"(published minimum 0, documented disable value) rejected "
                                    f"with {st}; raw: {str(raw)[:200]}"))
                continue
            try:
                env = json.loads(raw) if raw else {}
                ok_env = isinstance(env.get("result"), bool) and env["result"]
            except Exception:
                ok_env = False
            if not ok_env:
                findings.append((2, f"Type4_StateLogicViolation: {field}=0 leg 2xx but envelope "
                                    f"violates result:boolean=true grid; raw: {str(raw)[:200]}"))
                continue
            res, err = describe_result(name)
            got = walk(res, OCFG + [field]) if isinstance(res, dict) else None
            if got == 0:
                print(f"[conform] {field}=0 closure accepted and persisted")
            else:
                findings.append((2, f"Type4_StateLogicViolation: {field}=0 accepted but readback "
                                    f"optimizer_config.{field}={got!r} != 0"))
        # CONFLICT-ZONE measured-only legs (input diff grid vs resolved grid disagree)
        measured_leg("vacuum_min_vector_number=99 (contract/resolved min 100 vs diff min 0)",
                     {"vectors": DENSE, "optimizers_config": {"vacuum_min_vector_number": 99}},
                     "vacuum_min_vector_number", 99, findings)
        measured_leg("max_segment_size=0 (contract/resolved min 1 vs diff min 0)",
                     {"vectors": DENSE, "optimizers_config": {"max_segment_size": 0}},
                     "max_segment_size", 0, findings)
        measured_leg("deleted_threshold=1.5 (contract/resolved [0,1] vs diff unbounded)",
                     {"vectors": DENSE, "optimizers_config": {"deleted_threshold": 1.5}},
                     "deleted_threshold", 1.5, findings)

        if findings:
            findings.sort(key=lambda x: x[0])
            rank, msg = findings[0]
            if rank == 3:
                print(f"VERDICT: SCRIPT_ERROR - {msg}")
                sys.exit(2)
            print(f"VERDICT: DEFECT_FOUND ({msg})")
            sys.exit(1)
        print("OK: hard minima enforced (indexing/memmap); 0-closures persisted; "
              "conflict-zone dispositions printed measured-only")
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
