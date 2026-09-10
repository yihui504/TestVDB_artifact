#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_create_007
# strategy: behavioral_contract
# endpoint: collections+create
# constraint_ids: qdrant_type_collections_create_006
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (new 1.18 memory-placement enum trusted without probing the
#   documented dense-face exclusion of 'pinned')
"""
Attack: behavioral_contract x qdrant_type_collections_create_006
  (chunk_collections+create-1of2; PUT /collections/{name}, path_key
  create_collection from runtime PATHS, URL from raw_knowledge
  api_endpoints[collections+create].url). The assertion (evidence_tier=
  explicit, 1.18-specific): memory IN {cold, cached, pinned} on VectorParams;
  pinned is NOT supported for dense vector storage; memory replaces the
  deprecated on_disk/always_ram booleans. Probes (fresh name each, readback
  via describe result.config.params.vectors):
    - vectors.memory "cold" -> 200 + echo "cold" when the key is served
    - vectors.memory "cached" -> 200 + echo "cached" when served
    - vectors.memory "pinned" on a DENSE config -> must be refused 400/422
      (the documented dense-face exclusion; acceptance = the defect signal)
    - vectors.memory "hot" -> refused (out of enum)
    - vectors.memory "COLD" -> refused (case-sensitive wire value)
  [chunk_collections+create-1of2 coverage: behavioral_contract x
   qdrant_type_collections_create_006 (cold/cached closures + pinned-on-dense
   exclusion + 2 out-of-enum rejections)]
Oracle: 'cold' and 'cached' dense creates return 200 result=true (refusal =
  Type1_IllegalRejection) with params.vectors.memory echoing the member when
  served; 'pinned' on dense, 'hot' and 'COLD' are each refused 400/422 (any
  2xx = Type1_IllegalSuccess - in particular pinned-on-dense accepted would
  break the documented exclusion; 5xx with /healthz alive =
  Type3_RuntimeFailure) - constraint qdrant_type_collections_create_006.

Rationale (G4/G7): two in-enum members give the closure direction, and the
exclusion + two out-of-enum values give the violation direction; the pinned
case is the 1.18-new exclusion most likely to be unimplemented in validation
(new-field blind spot), which is why it is the primary defect probe.
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

PREFIX = "scc07_"
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


def create(name, body):
    st, raw = safe_request("PUT", "create_collection", body, path_params={"name": name})
    print(f"[create {name}] status={st} raw={str(raw)[:300]}")
    if st in (200, 201):
        CREATED.append(name)
    return st, raw


def describe_vectors(name):
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
    return params.get("vectors")


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


def check_envelope_true(raw, tag):
    b = jload(raw)
    if not isinstance(b, dict) or b.get("result") is not True:
        defect("Type4_StateLogicViolation",
               f"[{tag}] 200 body must carry result=true (response_shape "
               f"result:boolean); raw={str(raw)[:250]}")


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

        # ---- closures: cold, cached ----
        for member in ["cold", "cached"]:
            name = mkn(f"ok_{member}")
            st, raw = create(name, {"vectors": {"size": 4, "distance": "Cosine",
                                                "memory": member}})
            guard(st, raw, f"memory {member}")
            if st != 200:
                defect("Type1_IllegalRejection",
                       f"[memory {member}] documented memory member refused with {st}; "
                       f"constraint qdrant_type_collections_create_006 declares memory "
                       f"IN {{cold, cached, pinned}}; raw={str(raw)[:250]}")
            check_envelope_true(raw, f"memory {member}")
            vec = describe_vectors(name)
            echoed = vec.get("memory", "__absent__") if isinstance(vec, dict) else None
            print(f"[memory {member}] persisted echo = {echoed!r}")
            if echoed not in (member, "__absent__"):
                defect("Type4_StateLogicViolation",
                       f"[memory {member}] expected params.vectors.memory == "
                       f"{member!r} (or absent), got {echoed!r}")

        # ---- pinned on dense + out-of-enum: each must be refused ----
        cases = [
            ("pinned", "pinned",
             "memory 'pinned' on a DENSE vectors config (documented: pinned is "
             "not supported for dense vector storage)"),
            ("hot", "hot", "out-of-enum value 'hot'"),
            ("upper", "COLD", "case-violating spelling 'COLD'"),
        ]
        for tag, val, why in cases:
            name = mkn(f"bad_{tag}")
            st, raw = create(name, {"vectors": {"size": 4, "distance": "Cosine",
                                                "memory": val}})
            guard(st, raw, tag)
            if 200 <= st <= 299:
                defect("Type1_IllegalSuccess",
                       f"[{tag}] vectors.memory={val!r} ({why}) was ACCEPTED with "
                       f"status {st}; constraint qdrant_type_collections_create_006 "
                       f"(memory IN {{cold, cached, pinned}}; pinned not for dense "
                       f"storage); raw={str(raw)[:250]}")
            if st in (400, 422):
                print(f"[{tag}] cleanly rejected with {st}")
            else:
                script_error(f"[{tag}] unadjudicable refusal status {st} "
                             f"(expected 400/422); raw={str(raw)[:200]}")

        print("[summary] cold/cached closures accepted (+echo when served); "
              "pinned-on-dense, hot and COLD all refused - memory placement "
              "domain + dense-face pinned exclusion hold per "
              "qdrant_type_collections_create_006")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
