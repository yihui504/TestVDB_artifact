#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_create_003
# strategy: type_coercion
# endpoint: collections+create
# constraint_ids: qdrant_type_collections_create_002
# source_url: https://qdrant.tech/documentation/manage-data/vectors/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-01 (Parameter Type Coercion Trust - nested sparse_vectors map
#   assumed validated by serde; wrong container types and smuggled fields)
"""
Attack: type_coercion x qdrant_type_collections_create_002
  (chunk_collections+create-1of2; PUT /collections/{name}, path_key
  create_collection from runtime PATHS, URL from raw_knowledge
  api_endpoints[collections+create].url). The constraint (evidence_tier=
  explicit): sparse_vectors is a map of vector-name to SparseVectorParams, and
  sparse vector distance IS Dot and is NOT user-settable. Probes:
    - legal control: sparse_vectors {"text": {}} -> 200 + describe readback
      result.config.params.sparse_vectors (response_shape: object|null) holds
      the "text" key
    - distance smuggling: sparse_vectors {"text": {"distance": "Cosine"}} ->
      clean 4xx OR accepted-with-drop; readback must NOT show a user-set
      non-Dot distance. A persisted distance != "Dot" means the
      not-user-settable promise is broken. (A readback echoing distance="Dot"
      is normalization TO the mandated Dot - recorded, not a defect.)
    - wrong container/param types: sparse_vectors as list, as string, and
      {"text": 5} / {"text": []} (map value not an object) -> clean 4xx each
  [chunk_collections+create-1of2 coverage: type_coercion x
   qdrant_type_collections_create_002 (sparse map shape + distance
   not-user-settable enforcement)]
Oracle: {"text": {}} create 200 result=true with params.sparse_vectors holding
  "text"; the distance-smuggling case is refused 400/422 or its readback shows
  no non-Dot distance for "text" (persisted non-Dot distance = Type4/
  Type1 defect); all four wrong-type shapes are refused 400/422 (any 2xx =
  Type1_IllegalSuccess; 5xx with /healthz alive = Type3_RuntimeFailure) -
  constraint qdrant_type_collections_create_002.

Rationale (G4/G5/G7): the map grammar and the not-user-settable promise are
two independent assertions; each gets its own falsifiable disposition, and the
smuggling case is judged on persistence readback so a silent drop is not
misfiled as acceptance.
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

PREFIX = "scc03_"
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


def describe_sparse(name):
    """Readback per response_shape: result.config.params.sparse_vectors object|null."""
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
    return params.get("sparse_vectors")


def guard(st, raw, tag):
    """Common status guard: transport/5xx handling. Returns parsed body on 4xx."""
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

        # ---- legal control: {"text": {}} must be accepted + persisted ----
        name = mkn("ok_control")
        st, raw = create(name, {"vectors": DENSE, "sparse_vectors": {"text": {}}})
        guard(st, raw, "sparse control")
        if st != 200:
            defect("Type1_IllegalRejection",
                   f"[sparse control] legal sparse_vectors map {{\"text\": {{}}}} refused "
                   f"with {st}; constraint declares sparse_vectors a map of name to "
                   f"SparseVectorParams (all-optional params are legal); raw={str(raw)[:250]}")
        b = jload(raw)
        if not isinstance(b, dict) or b.get("result") is not True:
            defect("Type4_StateLogicViolation",
                   f"[sparse control] 200 body must carry result=true (response_shape "
                   f"result:boolean); raw={str(raw)[:250]}")
        sp = describe_sparse(name)
        print(f"[sparse control] persisted sparse_vectors = {sp!r}")
        if not isinstance(sp, dict) or "text" not in sp:
            defect("Type4_StateLogicViolation",
                   f"[sparse control] expected result.config.params.sparse_vectors to be "
                   f"an object holding key 'text' (response_shape declares "
                   f"params.sparse_vectors:object|null); got {sp!r}")

        # ---- distance smuggling: not-user-settable promise ----
        name = mkn("smuggle_distance")
        st, raw = create(name, {"vectors": DENSE,
                                "sparse_vectors": {"text": {"distance": "Cosine"}}})
        guard(st, raw, "distance smuggling")
        if st == 200:
            b = jload(raw)
            if not isinstance(b, dict) or b.get("result") is not True:
                defect("Type4_StateLogicViolation",
                       f"[distance smuggling] 200 body must carry result=true; "
                       f"raw={str(raw)[:250]}")
            sp = describe_sparse(name)
            print(f"[distance smuggling] persisted sparse_vectors = {sp!r}")
            node = sp.get("text") if isinstance(sp, dict) else None
            persisted = node.get("distance") if isinstance(node, dict) else None
            if persisted is not None and persisted != "Dot":
                defect("Type1_IllegalSuccess",
                       f"[distance smuggling] sparse distance IS user-settable: sent "
                       f"distance='Cosine' for sparse vector 'text' and the describe "
                       f"readback persisted distance={persisted!r} (!= 'Dot'); constraint "
                       f"qdrant_type_collections_create_002: sparse vector distance IS Dot "
                       f"and not user-settable")
            if persisted == "Dot":
                print("[distance smuggling] accepted but normalized to distance='Dot' "
                      "(the mandated value) - not-user-settable promise holds via "
                      "normalization; recorded")
            else:
                print("[distance smuggling] accepted with the smuggled field dropped "
                      "(readback shows no user distance) - not-user-settable promise holds")
        else:
            print(f"[distance smuggling] refused with {st} - not-user-settable promise "
                  f"holds via rejection")

        # ---- wrong container / param types: each must be refused ----
        cases = [
            ("list", ["text"], "sparse_vectors as list (map required)"),
            ("string", "text", "sparse_vectors as string (map required)"),
            ("value_int", {"text": 5}, "map value 5 (SparseVectorParams object required)"),
            ("value_list", {"text": []}, "map value [] (SparseVectorParams object required)"),
        ]
        for tag, sv, why in cases:
            name = mkn(f"bad_{tag}")
            st, raw = create(name, {"vectors": DENSE, "sparse_vectors": sv})
            guard(st, raw, tag)
            if 200 <= st <= 299:
                defect("Type1_IllegalSuccess",
                       f"[{tag}] {why} was ACCEPTED with status {st} (expected clean 4xx "
                       f"per qdrant_type_collections_create_002: sparse_vectors is a map "
                       f"of name to SparseVectorParams); raw={str(raw)[:250]}")
            if st in (400, 422):
                print(f"[{tag}] cleanly rejected with {st}")
            else:
                script_error(f"[{tag}] unadjudicable refusal status {st} "
                             f"(expected 400/422); raw={str(raw)[:200]}")

        print("[summary] legal sparse map accepted + persisted; distance smuggling "
              "held the not-user-settable promise; 4/4 wrong-type shapes refused - "
              "constraint qdrant_type_collections_create_002 holds")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
