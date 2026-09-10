#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_delete_005
# strategy: boundary (post-delete invisibility chain, both directions)
# endpoint: collections+delete
# constraint_ids: qdrant_bc_delete_invisibility_001
# source_url: https://qdrant.tech/documentation/manage-data/collections/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-04 Boundary Default Optimism (assuming the 200-ok delete
#   actually propagated to every read face; a ghost that survives on any face
#   is exactly the blindspot manifestation)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: invisibility-chain x qdrant_bc_delete_invisibility_001 on collections+delete (chunk_collections+delete unit behavioral_contracts::qdrant_bc_delete_invisibility_001)
Oracle: data-bearing collection (3 points upserted) verified visible on all
  three read faces (setup premise; its failure = SCRIPT_ERROR, never a defect,
  G8) -> DELETE -> 200 with envelope result:true -> immediately (no sleeps; the
  scenario's "(wait)" is honored by the confirmed-200 synchronous semantics):
  (1) GET /collections -> 200 and the name ABSENT from result.collections[].name
  (key extraction; presence = Type4_StateLogicViolation ghost listing);
  (2) GET /collections/{c} -> exactly 404 (raw_knowledge expected_responses
  declare 404 "not found"; 200/other = Type4 ghost details);
  (3) GET /collections/{c}/exists -> 200 with result.exists is False
  (CollectionExistence grid: exists:boolean required; exists=true = Type4 ghost
  existence; 404 = Type4 - the exists face declares "never 404 for missing
  collection, existence expressed in body" so a 404 fails this contract's
  "exists reports result.exists=false" expectation). 5xx with /healthz
  alive/dead = Type3; transport failure with healthy /healthz = SCRIPT_ERROR.
Unit detail: the contract's expected_behavior, quoted verbatim:
    "after a 200 delete, the list no longer contains the name, details access
     returns 404 and exists reports result.exists=false"
  Scenario (quoted): "create -> DELETE /collections/{c} (wait) ->
   GET /collections -> GET /collections/{c} -> GET /collections/{c}/exists".
  Positive pairing (G4): the pre-delete leg proves the three faces actually
  showed the collection before the delete, so post-delete invisibility is
  attributable to the delete, not to blind faces.

Path derivation note: GET /collections/{collection_name}/exists is not in the
  runtime PATHS table; its URL is registered verbatim from raw_knowledge
  api_endpoints[path=collections+exists].url (dispatch lesson: URLs from
  raw_knowledge api_endpoints[].url only) via the established rt.PATHS[key]
  extension pattern.
[chunk_collections+delete coverage: behavioral-positive x qdrant_behavioral_collections_delete_001
  = _001; behavioral-negative-404 x same assertion = _002; stateful double-delete
  x same assertion = _003; strategy4+7 malformed-names x same assertion = _004;
  invisibility-chain x qdrant_bc_delete_invisibility_001 (this script)]
Constraint: qdrant_bc_delete_invisibility_001
source_url: https://qdrant.tech/documentation/manage-data/collections/
doc_version: current (site latest; no version archive)

R11-lesson spec-grid cross-check (BEFORE oracle): raw_knowledge resolves the
three read faces as GET /collections -> 200 {result:{collections:
CollectionDescription[] of {name}}} (list membership extracted via the "name"
key - R11 lost a script to id-key parsing); GET /collections/{collection_name}
-> 200 {..., result: object} | 404 "not found"; GET
/collections/{collection_name}/exists -> 200 {result: CollectionExistence
{exists: boolean}}, "never 404 for missing collection (existence expressed in
body)". Delete face: DELETE /collections/{collection_name} -> 200
{result: boolean} | 404. Points upsert: PUT /collections/{name}/points with
{"points":[{id, vector}]}.
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

PFX = "bcd5" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix
DIM = 4
ASSERT = ("after a 200 delete, the list no longer contains the name, details "
          "access returns 404 and exists reports result.exists=false")


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


def envelope_result_true(raw):
    try:
        env = json.loads(raw) if raw else {}
    except Exception:
        return False
    return isinstance(env, dict) and isinstance(env.get("result"), bool) and env["result"]


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
                # key extraction first (R11 lesson: id-key parsing lost a script;
                # `name in colls` on object elements is a vacuous-true trap)
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
    name = PFX + "ghost"
    try:
        # ---- setup premise: data-bearing collection (create + 3 points) ----
        st, raw = safe_request("PUT", "create_collection",
                               body={"vectors": {"size": DIM, "distance": "Cosine"}},
                               path_params={"name": name}, timeout=60)
        print(f"[create {name}] status={st} raw={str(raw)[:300]}")
        if not transport_gate(f"create {name}", st, raw, findings):
            finish(findings)
            return
        if st not in (200, 201):
            findings.append((3, f"SCRIPT-ERROR-setup: create returned {st}: {str(raw)[:150]}"))
            finish(findings)
            return
        pts = [{"id": i, "vector": [0.1 * (i + 1), 0.2, 0.3, 0.4]} for i in range(3)]
        ust, uraw = safe_request("PUT", "upsert_points", body={"points": pts},
                                 path_params={"name": name}, timeout=60)
        print(f"[upsert 3 points] status={ust} raw={str(uraw)[:300]}")
        if not transport_gate("upsert points", ust, uraw, findings):
            finish(findings)
            return
        if ust not in (200, 201):
            findings.append((3, f"SCRIPT-ERROR-setup: upsert returned {ust}: {str(uraw)[:150]}"))
            finish(findings)
            return

        # ---- positive pairing (G4): all three faces must show it BEFORE delete ----
        # (failure here is a setup-premise failure, not a delete-contract defect)
        lst, lraw, names = list_names()
        print(f"[pre list] status={lst} name_present={names is not None and name in names} "
              f"raw={str(lraw)[:200]}")
        if lst != 200 or names is None or name not in names:
            findings.append((3, "SCRIPT-ERROR-setup: pre-delete list face did not show "
                                f"the collection (status={lst}, present={name in names if names is not None else '?'}): "
                                f"{str(lraw)[:150]}"))
        est, eraw, eval_ = exists_face(name)
        print(f"[pre exists] status={est} result.exists={eval_!r} raw={str(eraw)[:200]}")
        if est != 200 or eval_ is not True:
            findings.append((3, f"SCRIPT-ERROR-setup: pre-delete exists face did not "
                                f"report true (status={est}, exists={eval_!r})"))
        if any(r == 3 for r, _ in findings):
            finish(findings)
            return

        # ---- act: DELETE (premise of the contract) ----
        st, raw = safe_request("DELETE", "drop_collection",
                               path_params={"name": name}, timeout=120)
        print(f"[delete {name}] status={st} raw={str(raw)[:300]}")
        if not transport_gate(f"delete {name}", st, raw, findings):
            finish(findings)
            return
        if st != 200 or not envelope_result_true(raw):
            findings.append((2, f"Type4 disposition: delete returned {st} (envelope "
                                f"ok={envelope_result_true(raw)}); contract scenario "
                                f"premise is a 200 delete; raw: {str(raw)[:200]}"))
            finish(findings)
            return

        # ---- face 1 (immediately, no sleeps): list no longer contains the name ----
        lst, lraw, names = list_names()
        print(f"[post list] status={lst} n_names={'?' if names is None else len(names)} "
              f"name_present={names is not None and name in names} raw={str(lraw)[:200]}")
        if not transport_gate("post list face", lst, lraw, findings):
            pass
        elif names is None:
            findings.append((3, "SCRIPT-ERROR: post-delete list 200 but "
                                f"result.collections[].name unparseable: {str(lraw)[:150]}"))
        elif name in names:
            findings.append((2, f"Type4_StateLogicViolation: after a 200 delete, "
                                f"'{name}' is STILL PRESENT in the collections list "
                                f"(ghost listing)"))
        else:
            print(f"[conform] list face: '{name}' absent after the 200 delete")

        # ---- face 2: details access returns 404 ----
        gst, graw = safe_request("GET", "describe_collection",
                                 path_params={"name": name}, timeout=30)
        print(f"[post get] status={gst} raw={str(graw)[:200]}")
        if not transport_gate("post get face", gst, graw, findings):
            pass
        elif gst == 404:
            print("[conform] get face: 404 after the 200 delete (declared expectation)")
        elif gst == 200:
            findings.append((2, f"Type4_StateLogicViolation: after a 200 delete, GET "
                                f"details still returns 200 for '{name}' (ghost "
                                f"details): {str(graw)[:150]}"))
        else:
            findings.append((2, f"Type4_StateLogicViolation: after a 200 delete, GET "
                                f"details returned {gst} (expected the declared 404): "
                                f"{str(graw)[:150]}"))

        # ---- face 3: exists reports result.exists=false ----
        est, eraw, eval_ = exists_face(name)
        print(f"[post exists] status={est} result.exists={eval_!r} raw={str(eraw)[:200]}")
        if not transport_gate("post exists face", est, eraw, findings):
            pass
        elif est == 200 and eval_ is False:
            print("[conform] exists face: 200 with result.exists=false "
                  "(CollectionExistence grid)")
        elif est == 200 and eval_ is True:
            findings.append((2, f"Type4_StateLogicViolation: after a 200 delete, "
                                f"exists face still reports result.exists=true for "
                                f"'{name}' (ghost existence)"))
        elif est == 200:
            findings.append((3, "SCRIPT-ERROR: post-delete exists 200 but "
                                f"result.exists unparseable: {str(eraw)[:150]}"))
        elif est == 404:
            findings.append((2, "Type4_StateLogicViolation: after a 200 delete, exists "
                                f"face returned 404 - the contract requires it to "
                                f"report result.exists=false in the body (exists face "
                                f"declares never-404, existence expressed in body)"))
        else:
            findings.append((2, f"Type4_StateLogicViolation: after a 200 delete, exists "
                                f"face returned {est} (expected 200 + "
                                f"result.exists=false): {str(eraw)[:150]}"))
        finish(findings)
    finally:
        # deletes are destructive: this collection is ours - drop best-effort
        # (no-op if the leg under test already deleted it)
        try:
            rt.drop_collection(name)
        except Exception as e:
            print(f"cleanup warning (drop {name}): {e}")


def finish(findings):
    if findings:
        findings.sort(key=lambda x: x[0])
        rank, msg = findings[0]
        if rank == 3:
            print(f"VERDICT: SCRIPT_ERROR - {msg}")
            sys.exit(2)
        print(f"VERDICT: DEFECT_FOUND ({msg})")
        sys.exit(1)
    print("OK: 200-deleted data-bearing collection is absent from the list, "
          "details return 404 and exists reports result.exists=false (all faces "
          "shown to display the collection before the delete)")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)


if __name__ == "__main__":
    main()
