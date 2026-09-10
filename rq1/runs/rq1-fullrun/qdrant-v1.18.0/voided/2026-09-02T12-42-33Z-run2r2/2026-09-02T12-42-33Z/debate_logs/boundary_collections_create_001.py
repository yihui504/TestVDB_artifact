#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_create_001
# strategy: type_boundary (strategy 2)
# endpoint: collections+create
# constraint_ids: qdrant_type_collections_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 Parameter Type Coercion Trust (vectors config missing / vectors={} /
#   non-enum distance accepted silently is exactly the named blindspot manifestation)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-boundary x qdrant_type_collections_create_001 on collections+create
  (PUT /collections/{collection_name}; chunk_collections+create-1of2 unit
  constraints::qdrant_type_collections_create_001, evidence_tier=explicit). The
  constraint's assertion, quoted verbatim:
    "vectors.distance IN {Cosine, Euclid, Dot, Manhattan}; VectorParams.required =
     [size, distance]; vectors.size is an unsigned integer (uint64)"
  Legs (G4 both directions, one shared deployment, fresh collection per leg):
    negative (absent-config class, Pattern B expect_rejected): vectors={} (no vector
      space defined anywhere - BS-01 named probe), {"size":4} w/o distance, {"distance":
      "Cosine"} w/o size (VectorParams.required violation);
    negative (field-value class, Pattern B' judge_schema_attack): distance="Euclidean"
      (non-enum; threat model records 'Euclid' as the official enum name, so accepting
      the 'Euclidean' alias would violate the strict enum), size=-1 (uint64 violation),
      size="4" (string type confusion);
    positive closure: distance="Manhattan" (least-common enum member) -> 200 with
      envelope result:boolean=true and describe readback vectors.distance=="Manhattan".
[chunk_collections+create-1of2 coverage: strategy2 x qdrant_type_collections_create_001
  (this script); strategy2 x _002/_003/_004/_005/_006 = boundary_collections_create_002
  ..006; strategy1 x qdrant_range_collections_create_001..006 =
  boundary_collections_create_007..012]
Oracle: absent-config legs (vectors={} / missing size / missing distance) -> 4xx each
  (200 = Type1_IllegalSuccess: collection created with no compliant vector space);
  distance="Euclidean" / size=-1 / size="4" -> 4xx (200 + persisted-as-sent = Type1;
  200 + normalized value = Type2-signal, drop-with-default indistinguishable on this
  face, judge adjudicates); positive leg -> 200 with result:true(boolean envelope) and
  describe result.config.params.vectors.distance=="Manhattan" (any other readback =
  Type4_StateLogicViolation); legal-closure rejected with 4xx = Type4 disposition
  conflict; 5xx with /healthz alive or /healthz dead after 3 probes = Type3; transport
  failure with healthy /healthz = SCRIPT_ERROR.
Constraint: qdrant_type_collections_create_001
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
doc_version: 1.18.x (versioned v-1-18-x api-reference)

R8-lesson spec-grid cross-check (BEFORE oracle): the versioned v-1-18-x merged
OpenAPI (.sourcedeps local shard openapi.json, path /collections/{collection_name})
declares VectorParams required=[size,distance], size {integer, format: uint64},
distance enum [Cosine, Euclid, Dot, Manhattan] - the contract grid IS corroborated
by the published spec (no phantom grid). Response grid: {status:string, time:number,
result:boolean}; describe readback path result.config.params.vectors.{size,distance}.
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

PFX = "bcc01" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix
CREATED = []  # every attempted collection name; cleanup drops all (no list.remove)
DIM = 4
ASSERT = ("vectors.distance IN {Cosine, Euclid, Dot, Manhattan}; VectorParams.required "
          "= [size, distance]; vectors.size is an unsigned integer (uint64)")


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


def absent_leg(label, body, findings):
    """Pattern B (required-config absent): whole-request legality - expect_rejected."""
    name = PFX + "n" + str(len(CREATED))
    CREATED.append(name)
    st, raw = create(name, body)
    print(f"[{label}] status={st} raw={str(raw)[:300]}")
    if not transport_gate(label, st, raw, findings):
        return
    v = rt.expect_rejected(st, raw, setup_ok=True)
    if v == "DEFECT_FOUND":
        findings.append((0, f"Type1_IllegalSuccess: '{label}' ACCEPTED with {st} - constraint "
                            f"asserts VectorParams.required=[size,distance] (a collection with no "
                            f"compliant vector space must be rejected); raw: {str(raw)[:200]}"))
    elif v == "NO_DEFECT":
        print(f"[conform] '{label}' rejected with {st}")
    else:
        findings.append((3, f"SCRIPT-ERROR: '{label}' judge={v} status={st} raw={str(raw)[:150]}"))


def value_leg(label, body, attack_path, attack_value, findings):
    """Pattern B' (schema-class field illegal value): judge_schema_attack (expect_rejected
    forbidden per spec); verdict refined by printed readback comparison."""
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
            kind = ("Type2-signal (readback differs from sent - silent normalize, or "
                    "drop-with-default which is indistinguishable on this resolved-config "
                    "face; judge to adjudicate)")
        findings.append((0, f"{kind}: '{label}' accepted with {st}; sent={attack_value!r} "
                            f"persisted={persisted!r}; assertion: {ASSERT}"))
    elif v == "NO_DEFECT":
        if st in (200, 201):
            print(f"[conform*] '{label}' 200 but the attacked field was silent-dropped (lenient path)")
        else:
            print(f"[conform] '{label}' rejected with {st}")
    else:
        findings.append((3, f"SCRIPT-ERROR: '{label}' judge={v} status={st} raw={str(raw)[:150]}"))


def positive_leg(label, body, readback, findings):
    """Legal closure leg: judge_200 + envelope result:boolean + declared readback compare
    (readback = (path, expected, hard_adjudicated))."""
    name = PFX + "p" + str(len(CREATED))
    CREATED.append(name)
    st, raw = create(name, body)
    print(f"[{label}] status={st} raw={str(raw)[:300]}")
    if not transport_gate(label, st, raw, findings):
        return
    v = rt.judge_200(st, raw, setup_ok=True)
    if v == "DEFECT_FOUND":
        findings.append((2, f"Type4 disposition conflict: '{label}' documented-legal enum member "
                            f"rejected with {st}; raw: {str(raw)[:200]}"))
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
    path, expected, hard = readback
    res, err = describe_result(name)
    got = walk(res, path) if isinstance(res, dict) else None
    if got == expected:
        print(f"[conform] '{label}' 200; readback {'.'.join(path)}={got!r} (persisted as sent)")
    elif hard:
        findings.append((2, f"Type4_StateLogicViolation: '{label}' accepted but readback "
                            f"{'.'.join(path)}={got!r} != sent {expected!r}"))
    else:
        print(f"[observe-only] '{label}' readback {'.'.join(path)}={got!r} (sent {expected!r}) - measured, not adjudicated")


def main():
    print(f"ownership prefix: {PFX}")
    print(f"[constraint quote] {ASSERT}")
    findings = []
    try:
        # absent-config negatives (Pattern B)
        absent_leg("vectors={} (no vector space defined - BS-01)", {"vectors": {}}, findings)
        absent_leg("vectors={'size':4} distance missing", {"vectors": {"size": DIM}}, findings)
        absent_leg("vectors={'distance':'Cosine'} size missing",
                   {"vectors": {"distance": "Cosine"}}, findings)
        # field-value negatives (Pattern B')
        value_leg("distance='Euclidean' (non-enum alias)",
                  {"vectors": {"size": DIM, "distance": "Euclidean"}},
                  ["config", "params", "vectors", "distance"], "Euclidean", findings)
        value_leg("size=-1 (uint64 violation)",
                  {"vectors": {"size": -1, "distance": "Cosine"}},
                  ["config", "params", "vectors", "size"], -1, findings)
        value_leg("size='4' (string type confusion)",
                  {"vectors": {"size": "4", "distance": "Cosine"}},
                  ["config", "params", "vectors", "size"], "4", findings)
        # positive enum closure
        positive_leg("distance='Manhattan' (enum closure, least-common member)",
                     {"vectors": {"size": DIM, "distance": "Manhattan"}},
                     (["config", "params", "vectors", "distance"], "Manhattan", True), findings)

        if findings:
            findings.sort(key=lambda x: x[0])
            rank, msg = findings[0]
            if rank == 3:
                print(f"VERDICT: SCRIPT_ERROR - {msg}")
                sys.exit(2)
            print(f"VERDICT: DEFECT_FOUND ({msg})")
            sys.exit(1)
        print("OK: absent-config legs 4xx; illegal values rejected/dropped; enum closure persisted")
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
