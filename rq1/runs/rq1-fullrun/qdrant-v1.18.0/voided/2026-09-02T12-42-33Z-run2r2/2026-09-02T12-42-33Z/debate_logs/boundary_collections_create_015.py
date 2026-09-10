#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_create_015
# strategy: boundary (duplicate-name idempotency face)
# endpoint: collections+create
# constraint_ids: qdrant_behavioral_collections_create_002
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: duplicate-family x qdrant_behavioral_collections_create_002 on collections+create (chunk_collections+create-2of2 unit assertions::qdrant_behavioral_collections_create_002)
Oracle: re-PUT of an existing name (same body AND different body) -> 4xx family
  (409 observed; 400/401/403/405/406/408/409/410/412/413/415/422/429 accepted as the
  declared family) - 200 = Type1_IllegalSuccess ("never 200"); after the rejected
  duplicates the original config must be intact (describe readback
  result.config.params.vectors.{size,distance} unchanged; a reconfigured collection =
  Type4_StateLogicViolation); 5xx with /healthz alive/dead = Type3; transport failure
  with healthy /healthz = SCRIPT_ERROR.
Unit detail: PUT /collections/{collection_name}; evidence_tier=explicit,
  defect_type_if_violated=Type1_IllegalSuccess. The assertion's expected_behavior,
  quoted verbatim:
    "PUT an existing collection name returns an error in the 4xx family (409 observed
     on v1.18.0), never 200"

Adjudication note (G7 hand-written with declared expectation): rt.expect_rejected only
  adjudicates {400,422} as rejection - a healthy 409 (the assertion's OWN observed
  family) would be misclassified SCRIPT_ERROR by the generic helper, so the duplicate
  legs are adjudicated by an explicit expected-vs-actual family comparison here.
Legs (G4 pairing: the shared setup's first create is the positive control; G6
  mutation rationale: duplication at the identity boundary (same name) is the only
  mutation that can force the never-200 promise; the different-body variant checks
  the stronger no-silent-reconfigure side):
  setup: PUT A {"vectors":{size:4,distance:Cosine}} -> 200 (positive control);
  leg 1: PUT A same body -> 4xx;
  leg 2: PUT A different body (size:8, Euclid) -> 4xx;
  post-state: describe A -> original size=4/Cosine intact.
[chunk_collections+create-2of2 coverage: strategy6+1 x qdrant_resource_shard_number_001 =
  boundary_collections_create_013; envelope-positive x qdrant_behavioral_collections_create_001 =
  _014; duplicate-family x qdrant_behavioral_collections_create_002 (this script);
  enum/malformed x _003 = _016; cosine-normalization x _004 = _017; timeout-query x _005 =
  _018; visibility chain x qdrant_bc_create_visibility_001 = _019]
Constraint: qdrant_behavioral_collections_create_002
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
doc_version: 1.18.x (versioned v-1-18-x api-reference)

R8-lesson spec-grid cross-check (BEFORE oracle): the versioned v-1-18-x merged OpenAPI
(.sourcedeps local shard openapi.json) declares the create-collection error family
(4xx incl. 409 for already-exists, per the assertion's runtime observation on this very
binary) and the 200 grid {status:string, time:number, result:boolean}; describe readback
paths result.config.params.vectors.{size,distance}. The assertion's "409 observed
family; spec declares 4xx" wording marks this as a measured-family oracle.
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

PFX = "bcc15" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix
CREATED = []  # every attempted collection name; cleanup drops all (no list.remove)
DIM = 4
ASSERT = ("PUT an existing collection name returns an error in the 4xx family "
          "(409 observed on v1.18.0), never 200")
# declared 4xx family for this assertion (404 excluded on purpose: the path exists,
# so 404 would indicate a routing problem, not a rejection - runtime judge_4xx philosophy)
REJECT_FAMILY = {400, 401, 403, 405, 406, 408, 409, 410, 412, 413, 415, 422, 429}


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


def dup_family_verdict(label, st, raw, findings):
    """G7 hand-written adjudication with declared expectation vs actual:
    expected = 'error in the 4xx family (409 observed), never 200' (assertion text).
    Chosen over rt.expect_rejected because the generic helper admits only {400,422}
    and would misclassify a healthy 409 as SCRIPT_ERROR."""
    if st == 200:
        findings.append((0, f"Type1_IllegalSuccess: '{label}' re-create of an existing "
                            f"name returned 200 - assertion says 'never 200'; raw: {str(raw)[:200]}"))
    elif st in REJECT_FAMILY:
        print(f"[conform] '{label}' rejected with {st} (4xx family; 409 is the observed "
              f"member on this binary)")
    else:
        findings.append((3, f"SCRIPT-ERROR: '{label}' unexpected status {st} (outside the "
                            f"declared 4xx family); raw: {str(raw)[:150]}"))


def main():
    print(f"ownership prefix: {PFX}")
    print(f"[assertion quote] {ASSERT}")
    findings = []
    name = PFX + "dup"
    CREATED.append(name)
    body_a = {"vectors": {"size": DIM, "distance": "Cosine"}}
    body_b = {"vectors": {"size": 8, "distance": "Euclid"}}
    try:
        # setup / positive control: the first create must be accepted
        st, raw = create(name, body_a)
        print(f"[setup first create] status={st} raw={str(raw)[:300]}")
        if not transport_gate("setup first create", st, raw, findings):
            pass
        else:
            v = rt.judge_200(st, raw, setup_ok=True)
            if v == "DEFECT_FOUND":
                findings.append((2, f"Type4 disposition conflict: legal first create rejected "
                                    f"with {st}; raw: {str(raw)[:200]}"))
            else:
                try:
                    env = json.loads(raw) if raw else {}
                    ok_env = isinstance(env.get("result"), bool) and env["result"]
                except Exception:
                    ok_env = False
                if not ok_env:
                    findings.append((2, f"Type4_StateLogicViolation: first create 200 but "
                                        f"envelope violates result:boolean=true grid; raw: {str(raw)[:200]}"))

        # leg 1: duplicate name, identical body
        st, raw = create(name, body_a)
        print(f"[dup same-body] status={st} raw={str(raw)[:300]}")
        if transport_gate("dup same-body", st, raw, findings):
            dup_family_verdict("dup same-body", st, raw, findings)

        # leg 2: duplicate name, different body (no silent reconfigure)
        st, raw = create(name, body_b)
        print(f"[dup different-body] status={st} raw={str(raw)[:300]}")
        if transport_gate("dup different-body", st, raw, findings):
            dup_family_verdict("dup different-body", st, raw, findings)

        # post-state: original config must be intact after the rejected duplicates
        dst, draw = safe_request("GET", "describe_collection",
                                 path_params={"name": name}, timeout=30)
        print(f"[post-state describe] status={dst} raw={str(draw)[:200]}")
        if dst == 200:
            try:
                res = json.loads(draw).get("result")
            except Exception:
                res = None
            got_size = walk(res, ["config", "params", "vectors", "size"])
            got_dist = walk(res, ["config", "params", "vectors", "distance"])
            if got_size == DIM and got_dist == "Cosine":
                print(f"[conform] post-state intact: vectors.size={got_size!r} "
                      f"vectors.distance={got_dist!r} (rejected dups did not reconfigure)")
            else:
                findings.append((2, f"Type4_StateLogicViolation: after rejected duplicate "
                                    f"creates, config readback vectors.size={got_size!r} "
                                    f"distance={got_dist!r} != original {DIM}/Cosine "
                                    f"(silent reconfigure)"))
        elif dst > 0:
            findings.append((3, f"SCRIPT-ERROR: post-state describe returned {dst}: {str(draw)[:150]}"))
        else:
            v = healthz_ladder("post-state describe")
            if v:
                findings.append((1, v))

        if findings:
            findings.sort(key=lambda x: x[0])
            rank, msg = findings[0]
            if rank == 3:
                print(f"VERDICT: SCRIPT_ERROR - {msg}")
                sys.exit(2)
            print(f"VERDICT: DEFECT_FOUND ({msg})")
            sys.exit(1)
        print("OK: duplicate creates rejected in the 4xx family (never 200); original config intact")
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
