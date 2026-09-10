#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_create_019
# strategy: boundary (post-create visibility chain, both directions)
# endpoint: collections+create
# constraint_ids: qdrant_bc_create_visibility_001
# source_url: https://qdrant.tech/documentation/manage-data/collections/
# doc_version: current (site latest; no version archive)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: visibility-chain x qdrant_bc_create_visibility_001 on collections+create (chunk_collections+create-2of2 unit behavioral_contracts::qdrant_bc_create_visibility_001)
Oracle: immediately after a 200 create (no sleeps): GET /collections -> 200 with the
  name present in result.collections[].name (extracted via key extraction, not str
  membership on objects); GET /collections/{c} -> 200 with result.config an object
  (result.status observed-only - yellow/grey is contractually fine); GET
  /collections/{c}/exists -> 200 with result.exists is True. Any face failing while
  transport-healthy = Type4_StateLogicViolation (created-but-invisible). Negative
  control (G4, never-created name with this script's ownership prefix): absent from
  the list; describe -> 404 (raw_knowledge expected_responses declares 404 "not
  found"); exists -> 200 with result.exists is False (CollectionExistence grid) -
  result.exists=true on a never-created name = Type4 (phantom existence); a 404 on
  the exists face is conform-with-note (docs declare only 200 for exists - measured
  conflict zone, not adjudicated). 5xx with /healthz alive/dead = Type3; transport
  failure with healthy /healthz = SCRIPT_ERROR.
Unit detail: PUT /collections/{collection_name}. The contract's expected_behavior,
  quoted verbatim:
    "after a 200 create, the name appears in the collections list, details are
     retrievable (status may be yellow/grey while indexing) and exists reports
     result.exists=true"
  Scenario (quoted): "PUT /collections/{c} with a valid config returns 200 ->
   GET /collections -> GET /collections/{c} -> GET /collections/{c}/exists".

Path derivation note: GET /collections/{collection_name}/exists is not in the runtime
  PATHS table; its URL is registered verbatim from raw_knowledge
  api_endpoints[path=collections+exists].url (dispatch lesson: URLs from raw_knowledge
  api_endpoints[].url only) via the established rt.PATHS[key] extension pattern.
[chunk_collections+create-2of2 coverage: strategy6+1 x qdrant_resource_shard_number_001 =
  boundary_collections_create_013; envelope-positive x qdrant_behavioral_collections_create_001 =
  _014; duplicate-family x _002 = _015; enum/malformed x _003 = _016;
  cosine-normalization x _004 = _017; timeout-query x _005 = _018; visibility chain x
  qdrant_bc_create_visibility_001 (this script)]
Constraint: qdrant_bc_create_visibility_001
source_url: https://qdrant.tech/documentation/manage-data/collections/
doc_version: current (site latest; no version archive)

R8-lesson spec-grid cross-check (BEFORE oracle): the versioned v-1-18-x merged OpenAPI
(.sourcedeps local shard openapi.json) resolves the three read faces as:
GET /collections -> 200 {time:number, status:string, result: CollectionsResponse
{collections: CollectionDescription[] (required)}}; GET /collections/{collection_name}
-> 200 {..., result: object with config.params...} | 404 "not found";
GET /collections/{collection_name}/exists -> 200 {..., result: CollectionExistence
{exists: boolean (required)}}. The list-membership oracle extracts
result.collections[].name into a list before membership (R8 lesson: str-in on object
elements is a vacuous-true trap).
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

# exists face: URL registered verbatim from raw_knowledge api_endpoints
# [path=collections+exists].url (the runtime PATHS table has no key for it)
EXISTS_KEY = "collection_exists"
EXISTS_URL = "/collections/{collection_name}/exists"
if EXISTS_KEY not in rt.PATHS:
    rt.PATHS[EXISTS_KEY] = EXISTS_URL
print(f"[path derivation] {EXISTS_KEY} = {rt.PATHS[EXISTS_KEY]} "
      f"(raw_knowledge api_endpoints[collections+exists].url)")

PFX = "bcc19" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix
CREATED = []  # every attempted collection name; cleanup drops all (no list.remove)
DIM = 4
ASSERT = ("after a 200 create, the name appears in the collections list, details are "
          "retrievable (status may be yellow/grey while indexing) and exists reports "
          "result.exists=true")


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


def create(name):
    return safe_request("PUT", "create_collection",
                        body={"vectors": {"size": DIM, "distance": "Cosine"}},
                        path_params={"name": name}, timeout=60)


def list_names():
    """GET /collections -> (status, raw, names list extracted from
    result.collections[].name; None on parse failure)."""
    st, raw = safe_request("GET", "list_collections", timeout=30)
    names = None
    if st == 200:
        try:
            res = json.loads(raw).get("result")
            colls = res.get("collections") if isinstance(res, dict) else None
            if isinstance(colls, list):
                # key extraction first (R8 lesson: `name in colls` on object elements
                # is a vacuous-true trap)
                names = [c.get("name") for c in colls if isinstance(c, dict)]
        except Exception:
            names = None
    return st, raw, names


def exists_face(collection_name):
    """GET /collections/{collection_name}/exists -> (status, raw, exists_value)."""
    st, raw = safe_request("GET", EXISTS_KEY,
                           path_params={"collection_name": collection_name},
                           timeout=30)
    val = None
    if st == 200:
        try:
            res = json.loads(raw).get("result")
            if isinstance(res, dict):
                v = res.get("exists")
                if isinstance(v, bool):
                    val = v
        except Exception:
            val = None
    return st, raw, val


def main():
    print(f"ownership prefix: {PFX}")
    print(f"[contract quote] {ASSERT}")
    findings = []
    name = PFX + "vis"
    never = PFX + "never"  # never created by this script (or any script: unique PFX)
    CREATED.append(name)
    try:
        # premise: a valid create must return 200 (contract scenario premise)
        st, raw = create(name)
        print(f"[create {name}] status={st} raw={str(raw)[:300]}")
        if not transport_gate(f"create {name}", st, raw, findings):
            finish(findings)
            return
        v = rt.judge_200(st, raw, setup_ok=True)
        if v == "DEFECT_FOUND":
            findings.append((2, f"Type4 disposition conflict: valid create (contract "
                                f"scenario premise) rejected with {st}; raw: {str(raw)[:200]}"))
            finish(findings)
            return
        try:
            env = json.loads(raw) if raw else {}
            ok_env = isinstance(env.get("result"), bool) and env["result"]
        except Exception:
            ok_env = False
        if not ok_env:
            findings.append((2, f"Type4_StateLogicViolation: create 200 but envelope "
                                f"violates result:boolean=true grid; raw: {str(raw)[:200]}"))

        # ---- face 1: immediately listable (no sleeps) ----
        lst, lraw, names = list_names()
        print(f"[list face] status={lst} n_names={'?' if names is None else len(names)} "
              f"name_present={names is not None and name in names} raw={str(lraw)[:200]}")
        if not transport_gate("list face", lst, lraw, findings):
            pass
        elif names is None:
            findings.append((3, "SCRIPT-ERROR: list 200 but result.collections[].name "
                                f"unparseable: {str(lraw)[:150]}"))
        elif name not in names:
            findings.append((2, f"Type4_StateLogicViolation: after a 200 create, "
                                f"'{name}' is ABSENT from the collections list "
                                f"(created-but-invisible)"))
        else:
            print(f"[conform] list face: '{name}' present immediately after create")

        # ---- face 2: immediately gettable ----
        gst, graw = safe_request("GET", "describe_collection",
                                 path_params={"name": name}, timeout=30)
        try:
            gres = json.loads(graw).get("result") if gst == 200 else None
            gstatus = gres.get("status") if isinstance(gres, dict) else None
            gconfig = gres.get("config") if isinstance(gres, dict) else None
        except Exception:
            gres, gstatus, gconfig = None, None, None
        print(f"[get face] status={gst} result.status={gstatus!r} "
              f"config_is_object={isinstance(gconfig, dict)} raw={str(graw)[:200]}")
        if not transport_gate("get face", gst, graw, findings):
            pass
        elif gst != 200:
            findings.append((2, f"Type4_StateLogicViolation: after a 200 create, GET "
                                f"details returned {gst} (created-but-invisible): "
                                f"{str(graw)[:150]}"))
        elif not isinstance(gconfig, dict):
            findings.append((2, "Type4_StateLogicViolation: get face 200 but "
                                "result.config is not an object"))
        else:
            # result.status (green/yellow/grey) is contractually allowed to be
            # non-green while indexing - observed only, never adjudicated
            print(f"[conform] get face: details retrievable; result.status={gstatus!r} "
                  f"(yellow/grey contractually fine while indexing)")

        # ---- face 3: exists reports true ----
        est, eraw, eval_ = exists_face(name)
        print(f"[exists face] status={est} result.exists={eval_!r} raw={str(eraw)[:200]}")
        if not transport_gate("exists face", est, eraw, findings):
            pass
        elif est != 200:
            findings.append((2, f"Type4_StateLogicViolation: after a 200 create, exists "
                                f"face returned {est}: {str(eraw)[:150]}"))
        elif eval_ is not True:
            findings.append((2, f"Type4_StateLogicViolation: exists face 200 but "
                                f"result.exists={eval_!r} (contract requires true after "
                                f"a 200 create)"))
        else:
            print("[conform] exists face: result.exists=true")

        # ---- negative control: the faces must discriminate (never-created name) ----
        lst, lraw, names = list_names()
        phantom = names is not None and never in names
        print(f"[neg list] status={lst} phantom_listing={phantom}")
        if not transport_gate("neg list", lst, lraw, findings):
            pass
        elif lst == 200 and names is None:
            findings.append((3, "SCRIPT-ERROR: neg list 200 but unparseable: "
                                f"{str(lraw)[:150]}"))
        elif lst == 200 and phantom:
            findings.append((2, f"Type4_StateLogicViolation: never-created '{never}' "
                                f"appears in the collections list (phantom listing)"))
        elif lst == 200:
            print(f"[conform] neg list: never-created '{never}' absent")

        nst, nraw = safe_request("GET", "describe_collection",
                                 path_params={"name": never}, timeout=30)
        print(f"[neg get] status={nst} raw={str(nraw)[:200]}")
        if nst > 0 and nst != 404:
            # declared expectation per raw_knowledge expected_responses: 404 "not found"
            findings.append((3, f"SCRIPT-ERROR: neg get expected 404, got {nst}: "
                                f"{str(nraw)[:150]}"))
        elif nst == 404:
            print("[conform] neg get: 404 for never-created name (declared expectation)")
        else:
            vv = healthz_ladder("neg get")
            if vv:
                findings.append((1, vv))

        nst2, nraw2, neval = exists_face(never)
        print(f"[neg exists] status={nst2} result.exists={neval!r} raw={str(nraw2)[:200]}")
        if not transport_gate("neg exists", nst2, nraw2, findings):
            pass
        elif nst2 == 200 and neval is False:
            print("[conform] neg exists: 200 with result.exists=false (CollectionExistence grid)")
        elif nst2 == 200 and neval is True:
            findings.append((2, f"Type4_StateLogicViolation: exists face reports "
                                f"result.exists=true for never-created '{never}' "
                                f"(phantom existence)"))
        elif nst2 == 200:
            findings.append((3, f"SCRIPT-ERROR: neg exists 200 but result.exists "
                                f"unparseable: {str(nraw2)[:150]}"))
        elif nst2 == 404:
            # docs declare only 200 for this face - measured conflict zone, recorded
            # not adjudicated (R10 lesson: conflict zones measured-only)
            print("[conform-with-note] neg exists returned 404 (docs declare only 200 "
                  "for the exists face - measured, not adjudicated)")
        elif nst2 > 0:
            findings.append((3, f"SCRIPT-ERROR: neg exists unexpected status {nst2}: "
                                f"{str(nraw2)[:150]}"))

        finish(findings)
    finally:
        # data-bearing create endpoint: these collections are ours - drop best-effort
        for n in list(CREATED):
            try:
                rt.drop_collection(n)
            except Exception as e:
                print(f"cleanup warning (drop {n}): {e}")


def finish(findings):
    if findings:
        findings.sort(key=lambda x: x[0])
        rank, msg = findings[0]
        if rank == 3:
            print(f"VERDICT: SCRIPT_ERROR - {msg}")
            sys.exit(2)
        print(f"VERDICT: DEFECT_FOUND ({msg})")
        sys.exit(1)
    print("OK: 200-created collection immediately listable, gettable and exists=true; "
          "never-created control name invisible on all faces")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)


if __name__ == "__main__":
    main()
