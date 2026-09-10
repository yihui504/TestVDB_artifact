#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_create_023
# strategy: behavioral_contract
# endpoint: collections+create
# constraint_ids: qdrant_bc_create_visibility_001
# source_url: https://qdrant.tech/documentation/manage-data/collections/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-03-adjacent (async completion gaps - a 200 create whose
#   state is not yet visible to list/get/exists is the classic
#   completion-vs-visibility race)
"""
Attack: behavioral_contract x qdrant_bc_create_visibility_001
  (chunk_collections+create-2of2). The contract: a successfully created
  collection is IMMEDIATELY listable, gettable and reported as existing.
  Chain (no sleep between calls - 'immediately' is the oracle): PUT
  /collections/{c} 200 -> GET /collections (list) must contain the name ->
  GET /collections/{c} must return 200 with a result object whose
  result.status is present (yellow/grey while indexing are acceptable per
  the contract) -> GET /collections/{c}/exists must return
  result.exists==true. Negative pairing (G4): a never-created control
  name must be absent from the list, describe must 404, and exists must
  NOT report true (a false exists=true on a never-created name is a
  false-positive visibility defect).
  Face note: collections+exists has no runtime PATHS key; it is issued via
  the contract-derived REST face (FALLBACK markers below; URL =
  raw_knowledge api_endpoints[collections+exists].url =
  /collections/{collection_name}/exists, method GET, response_shape
  result.exists:boolean). The list face's contract response_shape carries
  a backfilled artifact (mirrors collections+get); extraction is therefore
  shape-tolerant (result.collections[].id preferred, result-as-list
  fallback) and the oracle is the membership fact, not the envelope.
  [chunk_collections+create-2of2 coverage: behavioral_contract x
   qdrant_bc_create_visibility_001 (immediate list/get/exists chain +
   never-created negative control)]
Oracle: after a 200 create, with zero intervening sleep, the collections
  list contains the name, describe returns 200 with result.status
  present, and exists returns 200 with result.exists==true - any miss on
  the three positive faces = Type4_StateLogicViolation (visibility
  contract); for the never-created control name, exists must not report
  true (result.exists==true or a 200-ghost describe = Type4_) and the
  list must not contain it (membership = Type4) - constraint
  qdrant_bc_create_visibility_001.

Rationale (G4/G7/D3b-1): the promise is a cross-endpoint state invariant;
  each face's extraction was aligned with its response_shape grid before
  writing (exists: result.exists boolean; describe: result object with
  status string), and the list face is judged on membership because its
  recorded shape is a known backfill conflict zone (measured-only, per
  standing lesson).
"""

import os
import sys
import json
import time
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
            _sd = str(_p)
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

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)
BASE_URL = BASE_URL.rstrip("/")

import requests  # noqa: E402  (used only by the exists fallback face below)

print("[path derivation] create_collection/describe_collection/list_collections = "
      "/collections[/{name}] (raw_knowledge api_endpoints[].url); exists face = "
      "/collections/{collection_name}/exists (raw_knowledge "
      "api_endpoints[collections+exists].url)")

PREFIX = "scc023_"
RUN = str(int(time.time()))
CREATED = []

_FB_PRINTED = [False]


def _fallback_markers():
    if _FB_PRINTED[0]:
        return
    _FB_PRINTED[0] = True
    print("FALLBACK_TRIGGERED: collections+exists (GET /collections/{collection_name}/exists) has no qdrant runtime PATHS key; issuing the contract-derived REST path via requests")
    print("[FALLBACK_JUSTIFIED: scripts/runtime/qdrant.py PATHS exposes create/describe/drop/list on /collections but no exists key, and the behavioral contract qdrant_bc_create_visibility_001 explicitly names collections+exists as a required face (result.exists=true); the route is derived 1:1 from raw_knowledge api_endpoints[collections+exists] (url /collections/{collection_name}/exists, method GET, response_shape result.exists:boolean, v-1-18-x api-reference) - same session pattern as the aliases+collection+list fallback face]")


def collection_exists_http(coll):
    """FALLBACK face: GET /collections/{collection_name}/exists -> (status, raw_text).
    Mirrors rt.request's 2-tuple so the rest of the script stays uniform."""
    _fallback_markers()
    url = BASE_URL + "/collections/" + str(coll) + "/exists"
    headers = {"Content-Type": "application/json"}
    _a = os.environ.get("TESTVDB_AUTH_HEADER", "")
    if _a:
        headers["Authorization"] = _a
    try:
        r = requests.get(url, headers=headers, timeout=30)
        return r.status_code, r.text
    except Exception as e:
        return 0, str(e)


def safe_request(method, path_key, body=None, path_params=None, query_params=None, timeout=60):
    """All other HTTP through the runtime; forwards method/path_key/body/
    path_params/query_params/timeout exactly (standing lesson)."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def jload(raw):
    try:
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}


def script_error(msg):
    print(f"VERDICT: SCRIPT_ERROR - {msg}")
    sys.exit(2)


def defect(dtype, msg):
    print(f"VERDICT: DEFECT_FOUND ({dtype})")
    print(msg)
    sys.exit(1)


def liveness(tag):
    hs, hraw = safe_request("GET", "healthz", timeout=15)
    print(f"[{tag}] /healthz probe status={hs} raw={str(hraw)[:120]}")
    return hs


def mkn(tag):
    return f"{PREFIX}{RUN}_{tag}"


def list_names():
    """Shape-tolerant list extraction: result.collections[].id preferred
    (v1.18.0 observed), result-as-list fallback. None = unparsable."""
    st, raw = safe_request("GET", "list_collections")
    print(f"[list] status={st} raw={str(raw)[:400]}")
    if st == 0:
        if liveness("transport-list") != 200:
            script_error("list transport failure and /healthz down; no defect conclusion")
        script_error("list transport failure; /healthz alive; no defect conclusion")
    if 500 <= st <= 599:
        if liveness("5xx-list") != 200:
            script_error(f"list 5xx ({st}) and /healthz not 200; deployment unstable")
        defect("Type3_RuntimeFailure",
               f"collections list raised {st} while /healthz alive; raw={str(raw)[:200]}")
    if st != 200:
        script_error(f"collections list returned {st}; raw={str(raw)[:200]}")
    b = jload(raw)
    res = b.get("result") if isinstance(b, dict) else None
    items = None
    if isinstance(res, dict) and isinstance(res.get("collections"), list):
        items = res["collections"]
    elif isinstance(res, list):
        items = res
    if items is None:
        script_error(f"collections list body has neither result.collections[] nor "
                     f"result[] (recorded shape conflict zone); raw={str(raw)[:250]}")
    names = []
    for it in items:
        if isinstance(it, dict) and "id" in it:
            names.append(it["id"])
        elif isinstance(it, str):
            names.append(it)
    return names


def cleanup():
    for n in list(CREATED):
        try:
            rt.drop_collection(n)
        except Exception:
            pass


def main():
    hs, hraw = safe_request("GET", "healthz", timeout=15)
    print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
    if hs != 200:
        script_error(f"/healthz pre-probe returned {hs}; deployment not reachable")

    try:
        pos = mkn("vis")
        neg = mkn("never_created")
        st, raw = safe_request("PUT", "create_collection",
                               {"vectors": {"size": 4, "distance": "Cosine"}},
                               path_params={"name": pos})
        print(f"[create {pos}] status={st} raw={str(raw)[:250]}")
        if st == 0:
            if liveness("transport") != 200:
                script_error("transport failure on create and /healthz down")
            script_error("transport failure on create; /healthz alive")
        if 500 <= st <= 599:
            if liveness("5xx") != 200:
                script_error(f"create 5xx ({st}) and /healthz not 200; deployment unstable")
            defect("Type3_RuntimeFailure",
                   f"create raised {st} while /healthz alive; raw={str(raw)[:200]}")
        if st not in (200, 201):
            script_error(f"create returned {st}; visibility chain needs a 200 create; raw={str(raw)[:200]}")
        CREATED.append(pos)
        print("[create] 200 - visibility clock starts NOW (no sleep before the faces)")

        # face 1: list membership, immediately
        names = list_names()
        print(f"[list] {len(names)} collections; membership pos={pos in names} neg={neg in names}")
        if pos not in names:
            defect("Type4_StateLogicViolation",
                   f"collection {pos} returned 200 on create but is ABSENT from the "
                   f"collections list queried immediately after - the immediate-"
                   f"listable promise of qdrant_bc_create_visibility_001 is violated "
                   f"(expected vs actual: listed vs absent); list head={names[:10]}")
        if neg in names:
            defect("Type4_StateLogicViolation",
                   f"never-created control name {neg} APPEARS in the collections list "
                   f"(false-positive visibility); list head={names[:10]}")

        # face 2: describe, immediately
        dst, draw = safe_request("GET", "describe_collection", path_params={"name": pos})
        print(f"[describe {pos}] status={dst} raw={str(draw)[:300]}")
        if dst == 0:
            if liveness("transport-describe") != 200:
                script_error("describe transport failure and /healthz down")
            script_error("describe transport failure; /healthz alive")
        if 500 <= dst <= 599:
            if liveness("5xx-describe") != 200:
                script_error(f"describe 5xx ({dst}) and /healthz not 200; deployment unstable")
            defect("Type3_RuntimeFailure",
                   f"describe of freshly created {pos} raised {dst} while /healthz alive")
        if dst != 200:
            defect("Type4_StateLogicViolation",
                   f"describe of freshly created {pos} returned {dst} (200 expected "
                   f"immediately after a 200 create per "
                   f"qdrant_bc_create_visibility_001); raw={str(draw)[:200]}")
        dres = jload(draw).get("result")
        dstat = dres.get("status") if isinstance(dres, dict) else None
        if not isinstance(dstat, str):
            defect("Type4_StateLogicViolation",
                   f"describe 200 of {pos} lacks result.status (response_shape "
                   f"result.status:string); got {dstat!r}; raw={str(draw)[:250]}")
        print(f"[describe] result.status={dstat!r} (yellow/grey/green all acceptable "
              f"while indexing per the contract - recorded, not claimed)")

        # face 3: exists, immediately (contract-derived fallback face)
        est, eraw = collection_exists_http(pos)
        print(f"[exists {pos}] status={est} raw={str(eraw)[:250]}")
        if est == 0:
            if liveness("transport-exists") != 200:
                script_error("exists transport failure and /healthz down")
            script_error("exists transport failure; /healthz alive")
        if 500 <= est <= 599:
            if liveness("5xx-exists") != 200:
                script_error(f"exists 5xx ({est}) and /healthz not 200; deployment unstable")
            defect("Type3_RuntimeFailure",
                   f"exists of freshly created {pos} raised {est} while /healthz alive")
        if est != 200:
            defect("Type4_StateLogicViolation",
                   f"exists of freshly created {pos} returned {est} (200 with "
                   f"result.exists=true expected per response_shape "
                   f"result.exists:boolean); raw={str(eraw)[:200]}")
        eres = jload(eraw).get("result")
        eexists = eres.get("exists") if isinstance(eres, dict) else None
        if eexists is not True:
            defect("Type4_StateLogicViolation",
                   f"exists of freshly created {pos} returned result.exists="
                   f"{eexists!r} (expected vs actual: True vs {eexists!r}); "
                   f"raw={str(eraw)[:250]}")
        print("[exists] result.exists == true - immediate existence confirmed")

        # negative control: never-created name must not be visible anywhere
        nst, nraw = collection_exists_http(neg)
        print(f"[exists-control {neg}] status={nst} raw={str(nraw)[:250]}")
        if nst == 200:
            nres = jload(nraw).get("result")
            nexists = nres.get("exists") if isinstance(nres, dict) else None
            if nexists is True:
                defect("Type4_StateLogicViolation",
                       f"exists reports result.exists==true for the NEVER-CREATED name "
                       f"{neg} - false-positive visibility; raw={str(nraw)[:250]}")
            print(f"[exists-control] result.exists={nexists!r} (false expected; "
                  f"any non-true non-crash disposition recorded)")
        else:
            print(f"[exists-control] status {nst} (non-200 disposition for a missing "
                  f"collection; recorded - the dangerous direction is exists=true, "
                  f"which did not occur)")
        ndst, ndraw = safe_request("GET", "describe_collection", path_params={"name": neg})
        print(f"[describe-control {neg}] status={ndst} raw={str(ndraw)[:150]}")
        if ndst == 200:
            defect("Type4_StateLogicViolation",
                   f"describe returns 200 for the never-created name {neg} - ghost "
                   f"collection visible; raw={str(ndraw)[:200]}")
        print("[describe-control] not visible (non-200) - negative control holds")

        print("[summary] created collection is immediately listable, gettable and "
              "exists=true; the never-created control is invisible on every face - "
              "contract qdrant_bc_create_visibility_001 holds")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
