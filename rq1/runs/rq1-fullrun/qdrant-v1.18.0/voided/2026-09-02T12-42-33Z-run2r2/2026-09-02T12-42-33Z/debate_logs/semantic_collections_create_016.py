#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_create_016
# strategy: behavioral_contract
# endpoint: collections+create
# constraint_ids: qdrant_behavioral_collections_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (documentation drift - success envelope must match the
#   spec-derived CollectionOperationResponse grid, not prose memory)
"""
Attack: behavioral_contract x qdrant_behavioral_collections_create_001
  (chunk_collections+create-2of2; PUT /collections/{name} via runtime
  path_key create_collection, URL from raw_knowledge
  api_endpoints[collections+create].url). The assertion (evidence_tier=
  explicit): successful creation returns 200 with CollectionOperationResponse
  (result, status, time) and 200 means the collection was created. Two-sided
  oracle per the endpoint response_shape grid (result:boolean,
  status:string, time:number): (1) the 200 success body must carry
  result==true (boolean identity), a string status, a numeric time;
  (2) the 200 claim must be state-backed - describe_collection immediately
  after must return 200 with result.config.params.vectors.size == the size
  sent (4) and distance == 'Cosine' (response_shape:
  result.config.params.vectors object). A 200 with result==false/absent, a
  mistyped status/time, or a describe that 404s / echoes a different config
  = the envelope lies about creation.
  [chunk_collections+create-2of2 coverage: behavioral_contract x
   qdrant_behavioral_collections_create_001 (success envelope shape +
   creation-backed closure)]
Oracle: valid create (vectors {size:4, distance:Cosine}) returns HTTP 200
  with body result==true (boolean), status a string, time a number - any
  missing/mistyped envelope field = Type4_StateLogicViolation; and the
  immediate describe returns 200 with result.config.params.vectors
  .size==4 and .distance=='Cosine' - a describe 404 or a config echo
  mismatch = Type4_StateLogicViolation; 4xx on the valid create =
  Type1_IllegalRejection; 5xx with /healthz alive = Type3_RuntimeFailure -
  constraint qdrant_behavioral_collections_create_001.

Rationale (G1/G7/D3b): the promise is the success contract itself; the
oracle was aligned with api_endpoints[collections+create].response_shape
(result boolean / status string / time number) and the describe grid
(result.config.params.vectors object) before writing - spec-derived fields
win over prose. Prior round covered type/range faces of this endpoint;
this is the envelope+state closure of the 200-means-created promise.
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

if not os.environ.get("TESTVDB_DB_URL"):
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)

print("[path derivation] create_collection = /collections/{name} "
      "(raw_knowledge api_endpoints[collections+create].url = /collections/{collection_name})")

PREFIX = "scc016_"
RUN = str(int(time.time()))
CREATED = []


def safe_request(method, path_key, body=None, path_params=None, query_params=None, timeout=60):
    """All HTTP through the runtime; forwards method/path_key/body/path_params/
    query_params/timeout exactly (standing lesson). Returns (status, raw_text)."""
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
        # control: deployment can create/describe at all
        ctl = mkn("ctl")
        ok, err = rt.setup_default(ctl, 4, "Cosine")
        if not ok:
            script_error(f"control setup_default failed: {err}")
        try:
            rt.drop_collection(ctl)
        except Exception:
            pass
        print("[control] setup_default create OK (deployment healthy)")

        # --- unit under test: success envelope + creation-backed closure ---
        name = mkn("ok_env")
        body = {"vectors": {"size": 4, "distance": "Cosine"}}
        st, raw = safe_request("PUT", "create_collection", body,
                               path_params={"name": name})
        print(f"[create {name}] status={st} raw={str(raw)[:300]}")
        if st == 0:
            if liveness("transport") != 200:
                script_error("transport failure on valid create and /healthz down; no defect conclusion")
            script_error("transport failure on valid create; /healthz alive; no defect conclusion")
        if 500 <= st <= 599:
            if liveness("5xx") != 200:
                script_error(f"valid create 5xx ({st}) and /healthz not 200; deployment unstable")
            defect("Type3_RuntimeFailure",
                   f"valid create raised server error {st} while /healthz is alive; "
                   f"raw={str(raw)[:200]}")
        if st not in (200, 201):
            defect("Type1_IllegalRejection",
                   f"valid create body {body} was refused with {st}; assertion "
                   f"qdrant_behavioral_collections_create_001 declares 200 for a "
                   f"valid create; raw={str(raw)[:250]}")
        CREATED.append(name)

        b = jload(raw)
        if not isinstance(b, dict):
            defect("Type4_StateLogicViolation",
                   f"200 create body is not a JSON object; CollectionOperationResponse "
                   f"expected (result/status/time); raw={str(raw)[:250]}")
        res = b.get("result")
        if res is not True:
            defect("Type4_StateLogicViolation",
                   f"200 create body must carry result==true (boolean; response_shape "
                   f"result:boolean), got {res!r}; expected vs actual: true vs {res!r}; "
                   f"raw={str(raw)[:250]}")
        stat = b.get("status")
        if not isinstance(stat, str):
            defect("Type4_StateLogicViolation",
                   f"200 create body must carry status as string (response_shape "
                   f"status:string), got {stat!r}; raw={str(raw)[:250]}")
        tm = b.get("time")
        if isinstance(tm, bool) or not isinstance(tm, (int, float)):
            defect("Type4_StateLogicViolation",
                   f"200 create body must carry time as number (response_shape "
                   f"time:number), got {tm!r}; raw={str(raw)[:250]}")
        print(f"[envelope] result==true (bool), status={stat!r} (str), time={tm!r} (number) - all conform")

        # creation-backed closure: the 200 must be state-backed
        dst, draw = safe_request("GET", "describe_collection", path_params={"name": name})
        print(f"[describe {name}] status={dst} raw={str(draw)[:300]}")
        if dst == 0:
            if liveness("transport") != 200:
                script_error("transport failure on describe and /healthz down; no defect conclusion")
            script_error("transport failure on describe; /healthz alive; no defect conclusion")
        if 500 <= dst <= 599:
            if liveness("5xx") != 200:
                script_error(f"describe 5xx ({dst}) and /healthz not 200; deployment unstable")
            defect("Type3_RuntimeFailure",
                   f"describe of freshly created {name} raised {dst} while /healthz alive; "
                   f"raw={str(draw)[:200]}")
        if dst == 404:
            defect("Type4_StateLogicViolation",
                   f"create returned 200 result=true but describe of {name} returns 404 - "
                   f"the success envelope is not backed by created state "
                   f"(200-means-created violated); raw={str(draw)[:200]}")
        if dst != 200:
            script_error(f"describe of {name} returned unexpected {dst}; raw={str(draw)[:200]}")
        d = jload(draw)
        dres = d.get("result") if isinstance(d, dict) else None
        if not isinstance(dres, dict):
            defect("Type4_StateLogicViolation",
                   f"describe 200 body lacks a result object (response_shape result:object); "
                   f"raw={str(draw)[:250]}")
        params = (dres.get("config") or {}).get("params") if isinstance(dres.get("config"), dict) else None
        vecs = params.get("vectors") if isinstance(params, dict) else None
        if not isinstance(vecs, dict):
            defect("Type4_StateLogicViolation",
                   f"describe 200 lacks result.config.params.vectors object "
                   f"(response_shape declares it); raw={str(draw)[:250]}")
        got_size = vecs.get("size")
        got_dist = vecs.get("distance")
        print(f"[echo] persisted vectors config = size={got_size!r} distance={got_dist!r}")
        if got_size != 4 or got_dist != "Cosine":
            defect("Type4_StateLogicViolation",
                   f"200 create claimed success but persisted config differs from the "
                   f"request: sent size=4 distance=Cosine, persisted size={got_size!r} "
                   f"distance={got_dist!r} (expected vs actual mismatch)")
        print(f"[state] collection {name} exists with the exact requested config - "
              f"200-means-created holds per qdrant_behavioral_collections_create_001")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
