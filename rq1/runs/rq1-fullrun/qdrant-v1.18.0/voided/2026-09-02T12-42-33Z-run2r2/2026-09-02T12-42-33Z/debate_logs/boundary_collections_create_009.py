#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_create_009
# strategy: boundary (strategy 1)
# endpoint: collections+create
# constraint_ids: qdrant_range_collections_create_003
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 Boundary Default Optimism (fractional bound documented in prose but
#   never schema-enforced is the classic silent-acceptance gap)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary-value x qdrant_range_collections_create_003 on collections+create
  (PUT /collections/{collection_name}; chunk_collections+create-1of2 unit
  constraints::qdrant_range_collections_create_003, evidence_tier=explicit). The
  constraint's assertion, quoted verbatim:
    "ScalarQuantization quantile within the closed interval [0.5, 1.0]"
  Legs (G4 both directions, fresh collection per leg, Pattern B' judge_schema_attack):
    negative: quantization_config.scalar.quantile=0.4 (below 0.5), quantile=1.1 (above
      1.0) - each inside a valid scalar {type: int8} wrapper (branch-required key
      present per raw_knowledge request_required_paths);
    positive closures: quantile=0.5 -> 200 + readback
      result.config.quantization_config.scalar.quantile==0.5; quantile=1.0 -> 200 +
      readback ==1.0 (both closed endpoints must be accepted).
  Provenance annotation (honesty over strength): the versioned OpenAPI schema for
  quantile carries NO minimum/maximum - the [0.5, 1.0] range is stated in the field
  description ("Expected value range in [0.5, 1.0]") and in this explicit-tier contract
  assertion. Acceptance of an out-of-range quantile with persistence therefore violates
  the documented expectation; the judge weighs description-level vs schema-level
  enforcement. Readbacks printed for grading.
[chunk_collections+create-1of2 coverage: strategy1 x qdrant_range_collections_create_003
  (this script); siblings 007/008/010..012 cover range_001/_002/_004.._006; 001..006
  cover strategy2 x type_001.._006]
Oracle: quantile=0.4 and quantile=1.1 -> 4xx each (200 + persisted-as-sent = Type1
  violation of the documented closed interval; 200 + clamped value = Type2-signal,
  judge adjudicates); quantile=0.5 and quantile=1.0 -> 200 result:true(boolean) +
  readback quantile==sent (other readback = Type4; legal closed-endpoint rejected 4xx =
  Type4 disposition conflict); 5xx with /healthz alive or dead-after-3-probes = Type3;
  transport failure with healthy /healthz = SCRIPT_ERROR.
Constraint: qdrant_range_collections_create_003
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
doc_version: 1.18.x (versioned v-1-18-x api-reference)

R8-lesson spec-grid cross-check (BEFORE oracle): the versioned v-1-18-x merged OpenAPI
ScalarQuantizationConfig declares quantile {number, double} with NO schema min/max and
description "Expected value range in [0.5, 1.0]"; required=[type] (enum ["int8"]).
Conflict-flavor annotation: contract asserts the closed interval explicitly; the
published schema does not machine-enforce it. Both closure legs use the schema-required
type key so a rejection can only be attributable to quantile itself.
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

PFX = "bcc09" + uuid.uuid4().hex[:6]
CREATED = []
DIM = 4
DENSE = {"size": DIM, "distance": "Cosine"}
ASSERT = "ScalarQuantization quantile within the closed interval [0.5, 1.0]"
QPATH = ["config", "quantization_config", "scalar", "quantile"]


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
        ("quantile=0.4 (below closed interval)", 0.4, "4xx"),
        ("quantile=1.1 (above closed interval)", 1.1, "4xx"),
        ("quantile=0.5 (closed lower endpoint)", 0.5, "2xx"),
        ("quantile=1.0 (closed upper endpoint)", 1.0, "2xx"),
    ]
    try:
        for label, q, expected in legs:
            name = PFX + "l" + str(len(CREATED))
            CREATED.append(name)
            body = {"vectors": DENSE,
                    "quantization_config": {"scalar": {"type": "int8", "quantile": q}}}
            st, raw = create(name, body)
            print(f"[{label}] status={st} raw={str(raw)[:300]}")
            if not transport_gate(label, st, raw, findings):
                break
            if expected == "4xx":
                v = rt.judge_schema_attack(st, raw, name, QPATH, q, setup_ok=True)
                if v == "DEFECT_FOUND":
                    res, err = describe_result(name)
                    persisted = walk(res, QPATH) if isinstance(res, dict) else None
                    if persisted == q:
                        kind = "Type1_IllegalSuccess (persisted as-is)"
                    else:
                        kind = ("Type2-signal (readback differs from sent - silent clamp; "
                                "judge to adjudicate description-level bound)")
                    findings.append((0, f"{kind}: '{label}' accepted with {st}; sent={q!r} "
                                        f"persisted={persisted!r}; assertion: {ASSERT}"))
                elif v == "NO_DEFECT":
                    if st in (200, 201):
                        print(f"[conform*] '{label}' 200 but quantile dropped (lenient path)")
                    else:
                        print(f"[conform] '{label}' rejected with {st}")
                else:
                    findings.append((3, f"SCRIPT-ERROR: '{label}' judge={v} status={st}"))
            else:
                v = rt.judge_200(st, raw, setup_ok=True)
                if v == "DEFECT_FOUND":
                    findings.append((2, f"Type4 disposition conflict: closed-endpoint quantile "
                                        f"{q} rejected with {st}; raw: {str(raw)[:200]}"))
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
                got = walk(res, QPATH) if isinstance(res, dict) else None
                # float compare on readback: qdrant echoes the double; compare with
                # exact equality first, fall back to isclose for representation noise
                if got == q or (isinstance(got, (int, float)) and abs(got - q) < 1e-9):
                    print(f"[conform] '{label}' 200; readback quantile={got!r}")
                else:
                    findings.append((2, f"Type4_StateLogicViolation: '{label}' accepted but "
                                        f"readback quantile={got!r} != sent {q!r}"))

        if findings:
            findings.sort(key=lambda x: x[0])
            rank, msg = findings[0]
            if rank == 3:
                print(f"VERDICT: SCRIPT_ERROR - {msg}")
                sys.exit(2)
            print(f"VERDICT: DEFECT_FOUND ({msg})")
            sys.exit(1)
        print("OK: out-of-interval quantiles rejected/clamped-noted; both closed endpoints persisted")
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
