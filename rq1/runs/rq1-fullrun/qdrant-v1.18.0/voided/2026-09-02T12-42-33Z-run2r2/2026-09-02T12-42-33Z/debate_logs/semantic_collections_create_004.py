#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_create_004
# strategy: behavioral_contract
# endpoint: collections+create
# constraint_ids: qdrant_type_collections_create_003
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - the concept-doc prose variant
#   'hash_slot' is NOT part of the v1.18.0 versioned spec enum; spec wins per
#   D3b, so accepting it would be drift enshrined in code)
"""
Attack: behavioral_contract x qdrant_type_collections_create_003
  (chunk_collections+create-1of2; PUT /collections/{name}, path_key
  create_collection from runtime PATHS, URL from raw_knowledge
  api_endpoints[collections+create].url). The assertion (evidence_tier=
  explicit): sharding_method IN {auto, custom} - versioned ShardingMethod
  enum, lowercase snake_case wire values. Probes:
    - 'auto' (fresh name) -> must be accepted 200 result=true; describe
      readback result.config.params.sharding_method (response_shape: any)
      echoes 'auto' when the key is served (absence recorded, measured-only)
    - 'custom' with shard_number=2 -> dual-acceptable disposition (accepted
      200, or clean 4xx on this standalone deployment); never 5xx; if
      accepted, readback must echo 'custom'
    - out-of-domain: 'hash_slot' (the doc-drift prose variant explicitly
      excluded from the v1.18.0 spec), 'CUSTOM' (case-sensitive wire value),
      1 (integer, not an enum string) -> each must be refused 400/422
  [chunk_collections+create-1of2 coverage: behavioral_contract x
   qdrant_type_collections_create_003 (auto accepted + echoed; custom
   dual-disposition; hash_slot/CUSTOM/1 refused)]
Oracle: 'auto' creates 200 result=true (refusal = Type1_IllegalRejection) and
  describe echoes sharding_method='auto' when served; 'custom'+shard_number=2
  answers 200 or a clean 400/422 (5xx with /healthz alive = Type3);
  'hash_slot', 'CUSTOM' and integer 1 are each refused 400/422 (any 2xx =
  Type1_IllegalSuccess) - constraint qdrant_type_collections_create_003.

Rationale (G3/G4/G7): 'custom' on a standalone node is deployment-conditional
(dual-acceptable, measured), while the enum-domain rejections and the 'auto'
closure are spec-anchored single-disposition claims; 'hash_slot' doubles as
the BS-05 doc-drift probe because the versioned spec explicitly excludes it.
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

PREFIX = "scc04_"
RUN = str(int(time.time()))
CREATED = []
DENSE = {"size": 4, "distance": "Cosine"}


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


def create(name, body):
    st, raw = safe_request("PUT", "create_collection", body, path_params={"name": name})
    print(f"[create {name}] status={st} raw={str(raw)[:300]}")
    if st in (200, 201):
        CREATED.append(name)
    return st, raw


def describe_sharding_method(name):
    st, raw = safe_request("GET", "describe_collection", path_params={"name": name})
    print(f"[describe {name}] status={st} raw={str(raw)[:300]}")
    if st != 200:
        script_error(f"describe of freshly created {name} returned {st}; readback unavailable")
    b = jload(raw)
    res = b.get("result") if isinstance(b, dict) else None
    if not isinstance(res, dict):
        script_error(f"describe of {name} returned no result object: raw={str(raw)[:200]}")
    cfg = res.get("config")
    if not isinstance(cfg, dict):
        script_error(f"describe of {name} returned no config object: raw={str(raw)[:200]}")
    params = cfg.get("params")
    if not isinstance(params, dict):
        script_error(f"describe of {name} returned no config.params object: raw={str(raw)[:200]}")
    return params.get("sharding_method", "__absent__")


def guard(st, raw, tag):
    """Common status guard: transport/5xx handling."""
    if st == 0:
        liveness("transport")
        script_error(f"transport failure on {tag}; no defect conclusion")
    if 500 <= st <= 599:
        if liveness("5xx") != 200:
            script_error(f"{tag} 5xx ({st}) and /healthz not 200; deployment unstable")
        defect("Type3_RuntimeFailure",
               f"[{tag}] server error {st} while /healthz is alive; raw={str(raw)[:200]}")


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
        ok, err = rt.setup_default(mkn("ctl"), 4, "Cosine")
        if not ok:
            script_error(f"control setup_default failed: {err}")
        print("[control] setup_default create OK (deployment healthy)")
        try:
            rt.drop_collection(mkn("ctl"))
        except Exception:
            pass

        # ---- 'auto': documented member, must be accepted + echoed ----
        name = mkn("ok_auto")
        st, raw = create(name, {"vectors": DENSE, "sharding_method": "auto"})
        guard(st, raw, "sharding_method auto")
        if st != 200:
            defect("Type1_IllegalRejection",
                   f"[sharding_method auto] documented enum member 'auto' refused with "
                   f"{st}; constraint qdrant_type_collections_create_003 declares "
                   f"sharding_method IN {{auto, custom}}; raw={str(raw)[:250]}")
        b = jload(raw)
        if not isinstance(b, dict) or b.get("result") is not True:
            defect("Type4_StateLogicViolation",
                   f"[sharding_method auto] 200 body must carry result=true (response_shape "
                   f"result:boolean); raw={str(raw)[:250]}")
        echoed = describe_sharding_method(name)
        print(f"[sharding_method auto] persisted echo = {echoed!r}")
        if echoed != "__absent__" and echoed != "auto":
            defect("Type4_StateLogicViolation",
                   f"[sharding_method auto] expected result.config.params.sharding_method "
                   f"== 'auto', got {echoed!r} (expected vs actual mismatch)")

        # ---- 'custom': deployment-conditional dual disposition ----
        name = mkn("ok_custom")
        st, raw = create(name, {"vectors": DENSE, "sharding_method": "custom",
                                "shard_number": 2})
        guard(st, raw, "sharding_method custom")
        if st == 200:
            b = jload(raw)
            if not isinstance(b, dict) or b.get("result") is not True:
                defect("Type4_StateLogicViolation",
                       f"[sharding_method custom] 200 body must carry result=true; "
                       f"raw={str(raw)[:250]}")
            echoed = describe_sharding_method(name)
            print(f"[sharding_method custom] accepted; persisted echo = {echoed!r}")
            if echoed != "__absent__" and echoed != "custom":
                defect("Type4_StateLogicViolation",
                       f"[sharding_method custom] expected params.sharding_method == "
                       f"'custom', got {echoed!r}")
            print("[sharding_method custom] accepted on this deployment (in-enum "
                  "member; disposition recorded)")
        elif st in (400, 422):
            print(f"[sharding_method custom] refused with {st} on this standalone "
                  f"deployment - clean refusal, dual-acceptable disposition recorded; "
                  f"raw={str(raw)[:200]}")
        else:
            script_error(f"[sharding_method custom] unadjudicable refusal status {st} "
                         f"(expected 200 or 400/422); raw={str(raw)[:200]}")

        # ---- out-of-domain values: each must be refused ----
        cases = [
            ("hash_slot", "hash_slot",
             "the concept-doc prose variant 'hash_slot' (explicitly NOT part of the "
             "v1.18.0 versioned ShardingMethod enum - spec wins over prose)"),
            ("upper", "CUSTOM", "case-violating spelling 'CUSTOM'"),
            ("int", 1, "integer 1 (enum string required)"),
        ]
        for tag, val, why in cases:
            name = mkn(f"bad_{tag}")
            st, raw = create(name, {"vectors": DENSE, "sharding_method": val})
            guard(st, raw, tag)
            if 200 <= st <= 299:
                defect("Type1_IllegalSuccess",
                       f"[{tag}] sharding_method={val!r} ({why}) was ACCEPTED with status "
                       f"{st}; the versioned enum is [auto, custom] only "
                       f"(qdrant_type_collections_create_003); raw={str(raw)[:250]}")
            if st in (400, 422):
                print(f"[{tag}] cleanly rejected with {st}")
            else:
                script_error(f"[{tag}] unadjudicable refusal status {st} "
                             f"(expected 400/422); raw={str(raw)[:200]}")

        print("[summary] 'auto' accepted + echoed; 'custom' dual-disposition recorded; "
              "'hash_slot'/'CUSTOM'/1 all refused - ShardingMethod enum domain holds "
              "per qdrant_type_collections_create_003")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
