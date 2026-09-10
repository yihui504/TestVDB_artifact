#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_delete_003
# strategy: behavioral_contract
# endpoint: collections+delete
# constraint_ids: qdrant_bc_delete_invisibility_001
# source_url: https://qdrant.tech/documentation/manage-data/collections/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-05 (Documentation Drift - the documented post-delete state is
#   a full disappearance on every read face; a drifting runtime that keeps a
#   deleted collection reachable on any single face violates the published
#   behavior)
"""
Attack: behavioral_contract (Type4) x qdrant_bc_delete_invisibility_001 on
  collections+delete (chunk_collections+delete unit
  behavioral_contracts::qdrant_bc_delete_invisibility_001).
  The contract, quoted verbatim:
    description: "a successfully deleted collection disappears from listing
                  and direct access returns 404"
    scenario:    "create -> DELETE /collections/{c} (wait) -> GET /collections
                  -> GET /collections/{c} -> GET /collections/{c}/exists"
    expected_behavior: "after a 200 delete, the list no longer contains the
                  name, details access returns 404 and exists reports
                  result.exists=false"
  This script walks exactly that scenario with G4 positive/negative pairing:
    pre-state  - immediately after create, ALL three faces must show PRESENCE
                 (list contains name, get 200 with result.config object,
                 exists result.exists=true); a broken pre-state is a setup
                 failure here (create-visibility is chunk_collections+create's
                 unit, already covered there) -> SCRIPT_ERROR, no defect claim
    delete     - DELETE with ?timeout=10 (the scenario's "(wait)": blocking
                 params travel in the query string - runtime lesson)
    post t0    - sampled with ZERO delay after the 200 ACK (the ACK-to-
                 propagation window is where a ghost face survives)
    post settle- re-sampled after a settle sleep
  [chunk_collections+delete coverage: behavioral_contract x
   qdrant_bc_delete_invisibility_001 (three-face invisibility chain with
   pre/post pairing and t0/settled sampling)]
Oracle: after a 200 delete (result=true envelope) the collection is absent on
  all three faces at BOTH samplings: list result.collections[].name does not
  contain it, GET /collections/{c} returns 404, GET /collections/{c}/exists
  returns 200 with result.exists=false; any face still showing the name /
  gettable / exists=true = Type4_StateLogicViolation (deleted-but-visible);
  5xx with /healthz alive = Type3; transport failure with healthy /healthz =
  SCRIPT_ERROR; a 404 from the exists face counts as absent-consistent with a
  measured conflict note (docs declare only 200 for that face - R10 lesson:
  conflict zones measured, not adjudicated).

Rationale (G1/G6/G7): the scenario's own three faces define the oracle; the
  mutation point (the delete ACK-to-propagation window) is where the
  invariant most easily breaks, so it is sampled explicitly before any
  settle delay.
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
print(f"[path derivation] drop_collection = /collections/{{name}} "
      f"(raw_knowledge api_endpoints[collections+delete].url); "
      f"{EXISTS_KEY} = {rt.PATHS[EXISTS_KEY]} (api_endpoints[collections+exists].url); "
      f"list_collections = /collections (api_endpoints[collections+list].url)")

PFX = "scd03" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix
DIM = 4
CREATED = []


def safe_request(method, path_key, **kw):
    """Thin delegation to rt.request (forwards body/path_params/query_params/
    timeout exactly - standing lesson)."""
    return rt.request(method, path_key, **kw)


def healthz_ladder(label, attempts=3, delay=2):
    for i in range(attempts):
        hs, hraw = safe_request("GET", "healthz", timeout=15)
        print(f"[healthz attempt {i + 1}] status={hs} raw={str(hraw)[:120]}")
        if 200 <= hs < 300:
            return None
        if i < attempts - 1:
            time.sleep(delay)
    return (f"Type3_RuntimeFailure(service-down) - '{label}': /healthz unreachable "
            f"after {attempts} attempts")


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


def list_names():
    """GET /collections -> (status, raw, names extracted from
    result.collections[].name; None on parse failure). Key extraction, never
    str-membership on object elements (R8 lesson)."""
    st, raw = safe_request("GET", "list_collections", timeout=30)
    names = None
    if st == 200:
        try:
            res = json.loads(raw).get("result")
            colls = res.get("collections") if isinstance(res, dict) else None
            if isinstance(colls, list):
                names = [c.get("name") for c in colls if isinstance(c, dict)]
        except Exception:
            names = None
    return st, raw, names


def get_face(name):
    st, raw = safe_request("GET", "describe_collection",
                           path_params={"name": name}, timeout=30)
    cfg = None
    if st == 200:
        try:
            res = json.loads(raw).get("result")
            if isinstance(res, dict):
                cfg = res.get("config")
        except Exception:
            cfg = None
    return st, raw, cfg


def exists_face(name):
    st, raw = safe_request("GET", EXISTS_KEY,
                           path_params={"collection_name": name}, timeout=30)
    val = None
    if st == 200:
        try:
            res = json.loads(raw).get("result")
            if isinstance(res, dict) and isinstance(res.get("exists"), bool):
                val = res["exists"]
        except Exception:
            val = None
    return st, raw, val


def sample(label, name, expect_present, findings):
    """Sample the three read faces once and adjudicate against the declared
    expectation (presence or absence). Returns True if all faces conformed."""
    ok = True
    lst, lraw, names = list_names()
    in_list = names is not None and name in names
    print(f"[{label} list] status={lst} name_present={in_list} raw={str(lraw)[:160]}")
    if not transport_gate(f"{label} list", lst, lraw, findings):
        return False
    if names is None:
        findings.append((3, f"SCRIPT-ERROR: {label} list 200 but "
                            f"result.collections[].name unparseable: {str(lraw)[:150]}"))
        return False
    if in_list != expect_present:
        findings.append((2, f"Type4_StateLogicViolation: {label} - collections list "
                            f"{'still contains' if in_list else 'does not contain'} "
                            f"'{name}' where {'presence' if expect_present else 'absence'} "
                            f"is required by qdrant_bc_delete_invisibility_001"))
        ok = False

    gst, graw, cfg = get_face(name)
    print(f"[{label} get] status={gst} config_is_object={isinstance(cfg, dict)} "
          f"raw={str(graw)[:160]}")
    if not transport_gate(f"{label} get", gst, graw, findings):
        return False
    if expect_present:
        if gst != 200 or not isinstance(cfg, dict):
            findings.append((3, f"SCRIPT-ERROR: {label} pre-state broken - get face did "
                                f"not return 200/config for a just-created collection "
                                f"(create-visibility unit owns that adjudication): "
                                f"{gst} {str(graw)[:120]}"))
            return False
    else:
        if gst == 200:
            findings.append((2, f"Type4_StateLogicViolation: {label} - deleted collection "
                                f"'{name}' still directly accessible (GET 200) per "
                                f"qdrant_bc_delete_invisibility_001"))
            ok = False
        elif gst != 404:
            print(f"[conflict-zone] {label} get: expected 404 for a deleted collection, "
                  f"got {gst}; measured, not adjudicated: {str(graw)[:120]}")

    est, eraw, ev = exists_face(name)
    print(f"[{label} exists] status={est} result.exists={ev} raw={str(eraw)[:160]}")
    if not transport_gate(f"{label} exists", est, eraw, findings):
        return False
    if expect_present:
        if est != 200 or ev is not True:
            findings.append((3, f"SCRIPT-ERROR: {label} pre-state broken - exists face "
                                f"did not report true for a just-created collection: "
                                f"{est}/{ev}"))
            return False
    else:
        if est == 200 and ev is True:
            findings.append((2, f"Type4_StateLogicViolation: {label} - exists face "
                                f"reports result.exists=true for deleted '{name}' "
                                f"(phantom existence)"))
            ok = False
        elif est == 200 and ev is False:
            print(f"[conform] {label} exists: 200 with result.exists=false")
        elif est == 404:
            print(f"[conflict-zone] {label} exists: 404 (docs declare only 200 for the "
                  f"exists face); counted absent-consistent, measured not adjudicated")
        else:
            print(f"[conflict-zone] {label} exists: status {est} with "
                  f"result.exists={ev!r}; measured, not adjudicated")
    return ok


def main():
    print(f"ownership prefix: {PFX}")
    findings = []
    name = PFX + "_inv"
    CREATED.append(name)
    try:
        hs, hraw = safe_request("GET", "healthz", timeout=15)
        print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
        if hs != 200:
            print(f"VERDICT: SCRIPT_ERROR - /healthz pre-probe returned {hs}")
            sys.exit(2)

        # ---- scenario step 1: create ----
        st, raw = safe_request("PUT", "create_collection",
                               body={"vectors": {"size": DIM, "distance": "Cosine"}},
                               path_params={"name": name}, timeout=60)
        print(f"[create {name}] status={st} raw={str(raw)[:200]}")
        if st != 200:
            print(f"VERDICT: SCRIPT_ERROR - create failed with {st} (setup premise)")
            sys.exit(2)

        # ---- pre-state: all faces PRESENT (G4 positive side) ----
        if not sample("pre", name, True, findings):
            finish(findings)
            return

        # ---- scenario step 2: DELETE (wait) ----
        st, raw = safe_request("DELETE", "drop_collection",
                               path_params={"name": name},
                               query_params={"timeout": 10}, timeout=60)
        print(f"[delete {name} ?timeout=10] status={st} raw={str(raw)[:250]}")
        if not transport_gate("delete", st, raw, findings):
            finish(findings)
            return
        try:
            env = json.loads(raw) if raw else {}
            ok_env = isinstance(env.get("result"), bool) and env["result"]
        except Exception:
            ok_env = False
        if st != 200:
            findings.append((3, f"SCRIPT-ERROR: delete of an existing collection got "
                                f"{st}; disposition matrix is the boundary lane's, "
                                f"invisibility chain cannot start: {str(raw)[:150]}"))
            finish(findings)
            return
        if not ok_env:
            findings.append((2, "Type4_StateLogicViolation: delete 200 but envelope "
                                "violates result:boolean=true grid "
                                "(collections+delete response_shape)"))

        # ---- post t0: all faces ABSENT, zero delay after the 200 ACK ----
        ok_t0 = sample("post-t0", name, False, findings)

        # ---- post settle: re-sample after a settle sleep ----
        time.sleep(2.5)
        ok_settled = sample("post-settle", name, False, findings)

        if ok_t0 and ok_settled:
            print("[summary] deleted collection invisible on list/get/exists at both "
                  "t0 and settled samplings per qdrant_bc_delete_invisibility_001")
        finish(findings)
    finally:
        # destructive-safety: only self-created, PFX-prefixed names are dropped
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
    print("OK: after a 200 delete the collection disappeared from the list, GET "
          "returns 404 and exists reports result.exists=false (sampled at t0 and "
          "after settle)")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)


if __name__ == "__main__":
    main()
