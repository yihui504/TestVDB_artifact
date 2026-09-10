#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_create_008
# strategy: boundary (strategy 1)
# endpoint: collections+create
# constraint_ids: qdrant_range_collections_create_002
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 Boundary Default Optimism (per-field minima trusted without
#   validation; below-minimum HNSW knobs silently accepted change index behavior)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary-value x qdrant_range_collections_create_002 on collections+create
  (PUT /collections/{collection_name}; chunk_collections+create-1of2 unit
  constraints::qdrant_range_collections_create_002, evidence_tier=explicit). The
  constraint's assertion, quoted verbatim:
    "hnsw_config (create, HnswConfigDiff schema): m minimum 0; ef_construct minimum 4;
     full_scan_threshold minimum 10 (KB); max_indexing_threads minimum 0; payload_m
     minimum 0"
  Legs (G4 both directions, fresh collection per leg):
    negative (Pattern B' judge_schema_attack): hnsw_config.ef_construct=3 (min-1),
      hnsw_config.m=-1 (min-1), hnsw_config.full_scan_threshold=9 (min-1);
    positive closure (ONE all-minima combo create): {m:0, ef_construct:4,
      full_scan_threshold:10, max_indexing_threads:0, payload_m:0} -> 200 with envelope
      result:boolean=true and readback result.config.hnsw_config.ef_construct==4 (hard);
      the other minima readbacks are printed observations (resolved-config asymmetries
      annotated below).
  Asymmetry annotation (spec-verified): the create-side HnswConfigDiff grid (which this
  constraint cites) says full_scan_threshold min 10; the resolved describe-side HnswConfig
  grid says min 0. The contract+input grid agree -> hard oracle for the 9 leg stands;
  the combo leg's full_scan_threshold readback is observation-only.
[chunk_collections+create-1of2 coverage: strategy1 x qdrant_range_collections_create_002
  (this script); siblings 007/009..012 cover range_001/_003.._006; 001..006 cover
  strategy2 x type_001.._006]
Oracle: ef_construct=3 / m=-1 / full_scan_threshold=9 -> 4xx each (200 + persisted-as-
  sent = Type1_IllegalSuccess; 200 + coerced legal value = Type2-signal, judge
  adjudicates); all-minima combo -> 200 result:true(boolean) + readback
  hnsw_config.ef_construct==4 (other ef_construct readback = Type4; missing = Type4);
  any single documented-minimum rejected as part of the combo (4xx) = Type4 disposition
  conflict (published HnswConfigDiff minima say all-legal); 5xx with /healthz alive or
  dead-after-3-probes = Type3; transport failure with healthy /healthz = SCRIPT_ERROR.
Constraint: qdrant_range_collections_create_002
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
doc_version: 1.18.x (versioned v-1-18-x api-reference)

R8-lesson spec-grid cross-check (BEFORE oracle): the versioned v-1-18-x merged OpenAPI
HnswConfigDiff (the create-side schema this constraint names) declares m {minimum: 0},
ef_construct {minimum: 4}, full_scan_threshold {minimum: 10}, max_indexing_threads
{minimum: 0} (0 = auto), payload_m {minimum: 0} - the contract grid IS corroborated
member-for-member by the published input schema. Describe readback path:
result.config.hnsw_config.{m,ef_construct,full_scan_threshold,max_indexing_threads,payload_m}.
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

PFX = "bcc08" + uuid.uuid4().hex[:6]
CREATED = []
DIM = 4
DENSE = {"size": DIM, "distance": "Cosine"}
ASSERT = ("hnsw_config (create, HnswConfigDiff schema): m minimum 0; ef_construct minimum 4; "
          "full_scan_threshold minimum 10 (KB); max_indexing_threads minimum 0; payload_m minimum 0")


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


def main():
    print(f"ownership prefix: {PFX}")
    print(f"[constraint quote] {ASSERT}")
    findings = []
    try:
        value_leg("hnsw_config.ef_construct=3 (min-1)",
                  {"vectors": DENSE, "hnsw_config": {"ef_construct": 3}},
                  ["config", "hnsw_config", "ef_construct"], 3, findings)
        value_leg("hnsw_config.m=-1 (min-1)",
                  {"vectors": DENSE, "hnsw_config": {"m": -1}},
                  ["config", "hnsw_config", "m"], -1, findings)
        value_leg("hnsw_config.full_scan_threshold=9 (min-1)",
                  {"vectors": DENSE, "hnsw_config": {"full_scan_threshold": 9}},
                  ["config", "hnsw_config", "full_scan_threshold"], 9, findings)

        # positive closure: ALL documented minima in one create
        name = PFX + "p0"
        CREATED.append(name)
        combo = {"m": 0, "ef_construct": 4, "full_scan_threshold": 10,
                 "max_indexing_threads": 0, "payload_m": 0}
        st, raw = create(name, {"vectors": DENSE, "hnsw_config": combo})
        print(f"[positive all-minima combo {json.dumps(combo)}] status={st} raw={str(raw)[:300]}")
        if transport_gate("positive all-minima combo", st, raw, findings):
            v = rt.judge_200(st, raw, setup_ok=True)
            if v == "DEFECT_FOUND":
                findings.append((2, f"Type4 disposition conflict: all-minima combo (every value "
                                    f"at its published HnswConfigDiff minimum) rejected with {st}; "
                                    f"raw: {str(raw)[:200]}"))
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
                    hc = walk(res, ["config", "hnsw_config"]) if isinstance(res, dict) else None
                    print(f"[readback] config.hnsw_config={json.dumps(hc)[:300]}")
                    ef = walk(res, ["config", "hnsw_config", "ef_construct"]) \
                        if isinstance(res, dict) else None
                    if ef == 4:
                        print("[conform] all-minima combo accepted; ef_construct=4 persisted (hard leg)")
                    else:
                        findings.append((2, f"Type4_StateLogicViolation: combo accepted but readback "
                                            f"hnsw_config.ef_construct={ef!r} != 4 (sent 4)"))
                    for f, sent in (("m", 0), ("full_scan_threshold", 10),
                                    ("max_indexing_threads", 0), ("payload_m", 0)):
                        got = walk(res, ["config", "hnsw_config", f]) if isinstance(res, dict) else None
                        print(f"[observe-only] hnsw_config.{f}: sent={sent} readback={got!r} "
                              f"(resolved-config asymmetries are annotated, not adjudicated)")

        if findings:
            findings.sort(key=lambda x: x[0])
            rank, msg = findings[0]
            if rank == 3:
                print(f"VERDICT: SCRIPT_ERROR - {msg}")
                sys.exit(2)
            print(f"VERDICT: DEFECT_FOUND ({msg})")
            sys.exit(1)
        print("OK: below-minimum hnsw values rejected/clamped-noted; all-minima combo accepted")
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
