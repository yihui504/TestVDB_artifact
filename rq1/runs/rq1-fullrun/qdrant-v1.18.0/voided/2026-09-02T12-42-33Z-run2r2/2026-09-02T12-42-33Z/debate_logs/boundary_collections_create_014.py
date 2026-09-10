#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_create_014
# strategy: boundary (positive envelope-shape closure)
# endpoint: collections+create
# constraint_ids: qdrant_behavioral_collections_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: envelope-positive x qdrant_behavioral_collections_create_001 on collections+create (chunk_collections+create-2of2 unit assertions::qdrant_behavioral_collections_create_001)
Oracle: both legal VectorsConfig oneOf branches -> 200 with envelope result:boolean==true,
  status:string, time:number (contract response_shape grid), and describe 200 proving
  "200 means created"; 4xx on a legal body = Type4 disposition conflict; 200 with a
  malformed envelope (result not a true boolean / status not string / time not number)
  = Type4_StateLogicViolation; readback of the named branch must return
  result.config.params.vectors.img.{size,distance} as sent.
Unit detail: PUT /collections/{collection_name}; evidence_tier=explicit.
  The assertion's expected_behavior, quoted verbatim:
    "valid create request returns HTTP 200 with an ok status; 200 means the collection was created"

Legs (G4 positive promise on both oneOf faces of VectorsConfig - R10 lesson:
  oneOf/single-key body forms):
  leg A (unnamed VectorParams branch): {"vectors": {"size": 4, "distance": "Cosine"}};
  leg B (named-map branch): {"vectors": {"img": {"size": 4, "distance": "Dot"}}}.
[chunk_collections+create-2of2 coverage: strategy6+1 x qdrant_resource_shard_number_001 =
  boundary_collections_create_013; envelope-positive x qdrant_behavioral_collections_create_001
  (this script); duplicate-family x _002 = _015; enum/malformed x _003 = _016;
  cosine-normalization x _004 = _017; timeout-query x _005 = _018; visibility chain x
  qdrant_bc_create_visibility_001 = _019]
Constraint: qdrant_behavioral_collections_create_001
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
doc_version: 1.18.x (versioned v-1-18-x api-reference)

R8-lesson spec-grid cross-check (BEFORE oracle): the versioned v-1-18-x merged OpenAPI
(.sourcedeps local shard openapi.json) declares the create-collection 200 response as
{time: number(double), status: string, result: boolean, usage: object?} - matching the
contract response_shape grid {time:number, status:string, result:boolean}; VectorsConfig
is the untagged oneOf {VectorParams | map<string,VectorParams>}, so both legs exercise
distinct legal branches. Describe readback path for the named branch:
result.config.params.vectors.img.{size,distance}.
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

PFX = "bcc14" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix
CREATED = []  # every attempted collection name; cleanup drops all (no list.remove)
DIM = 4
ASSERT = ("valid create request returns HTTP 200 with an ok status; 200 means the "
          "collection was created")


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


def create(name, body):
    return safe_request("PUT", "create_collection", body=body,
                        path_params={"name": name}, timeout=60)


def walk(node, path):
    for k in path:
        if isinstance(node, dict):
            node = node.get(k)
        else:
            return None
    return node


def envelope_defects(raw):
    """Declared-expectation comparison against the contract response_shape grid
    {result: boolean, status: string, time: number}. Returns a list of violation
    descriptions (empty = conforming envelope)."""
    bad = []
    try:
        env = json.loads(raw) if raw else {}
    except Exception:
        return [f"200 body is not JSON: {str(raw)[:120]}"]
    if not isinstance(env, dict):
        return [f"200 body is not an object: {str(raw)[:120]}"]
    res = env.get("result")
    if not (isinstance(res, bool) and res):
        bad.append(f"result={res!r} violates result:boolean==true")
    stat = env.get("status")
    if not isinstance(stat, str) or not stat:
        bad.append(f"status={stat!r} violates status:string")
    tm = env.get("time")
    if not isinstance(tm, (int, float)) or isinstance(tm, bool):
        bad.append(f"time={tm!r} violates time:number")
    return bad


def positive_leg(label, body, readback, findings):
    """Legal-branch leg: judge_200 + envelope grid compare + declared readbacks
    (readback = list of (path, expected) or None for the unnamed branch's face check)."""
    name = PFX + "p" + str(len(CREATED))
    CREATED.append(name)
    st, raw = create(name, body)
    print(f"[{label}] status={st} raw={str(raw)[:300]}")
    if not transport_gate(label, st, raw, findings):
        return
    v = rt.judge_200(st, raw, setup_ok=True)
    if v == "DEFECT_FOUND":
        findings.append((2, f"Type4 disposition conflict: '{label}' documented-legal body "
                            f"rejected with {st}; raw: {str(raw)[:200]}"))
        return
    bad = envelope_defects(raw)
    if bad:
        findings.append((2, f"Type4_StateLogicViolation: '{label}' 200 but envelope violates "
                            f"the response grid ({'; '.join(bad)}); raw: {str(raw)[:200]}"))
        return
    # "200 means the collection was created": describe must confirm existence
    dst, draw = safe_request("GET", "describe_collection",
                             path_params={"name": name}, timeout=30)
    if dst != 200:
        findings.append((2, f"Type4_StateLogicViolation: '{label}' create 200 but describe "
                            f"returns {dst}: 200 did not mean created; raw: {str(draw)[:200]}"))
        return
    try:
        res = json.loads(draw).get("result")
    except Exception:
        res = None
    if readback is not None:
        mismatch = []
        for path, expected in readback:
            got = walk(res, path)
            if got != expected:
                mismatch.append(f"{'.'.join(path)}={got!r} != sent {expected!r}")
        if mismatch:
            findings.append((2, f"Type4_StateLogicViolation: '{label}' accepted but readback "
                                f"mismatch ({'; '.join(mismatch)})"))
        else:
            print(f"[conform] '{label}' 200; envelope grid OK; readbacks as sent: "
                  + "; ".join(f"{'.'.join(pa)}={ex!r}" for pa, ex in readback))
    else:
        ok_face = isinstance(res, dict) and isinstance(res.get("config"), dict)
        if ok_face:
            print(f"[conform] '{label}' 200; envelope grid OK; describe confirms "
                  f"result.config present (collection created)")
        else:
            findings.append((2, f"Type4_StateLogicViolation: '{label}' create 200 but describe "
                                f"result.config missing/malformed: {str(draw)[:200]}"))


def main():
    print(f"ownership prefix: {PFX}")
    print(f"[assertion quote] {ASSERT}")
    findings = []
    try:
        positive_leg("unnamed VectorParams branch (vectors={size,distance})",
                     {"vectors": {"size": DIM, "distance": "Cosine"}}, None, findings)
        positive_leg("named-map VectorsConfig branch (vectors={img:{size,distance}})",
                     {"vectors": {"img": {"size": DIM, "distance": "Dot"}}},
                     [(["config", "params", "vectors", "img", "size"], DIM),
                      (["config", "params", "vectors", "img", "distance"], "Dot")],
                     findings)

        if findings:
            findings.sort(key=lambda x: x[0])
            rank, msg = findings[0]
            if rank == 3:
                print(f"VERDICT: SCRIPT_ERROR - {msg}")
                sys.exit(2)
            print(f"VERDICT: DEFECT_FOUND ({msg})")
            sys.exit(1)
        print("OK: both legal VectorsConfig branches -> 200 with conforming "
              "{result:boolean, status:string, time:number} envelope and created state")
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
