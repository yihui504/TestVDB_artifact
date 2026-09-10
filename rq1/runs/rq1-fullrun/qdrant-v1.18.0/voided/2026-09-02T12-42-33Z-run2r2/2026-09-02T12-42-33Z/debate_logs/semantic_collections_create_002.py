#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_create_002
# strategy: behavioral_contract
# endpoint: collections+create
# constraint_ids: qdrant_type_collections_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (enum-value-domain trust; strictness of the Distance enum
#   wire values) + threat-model by-design note: 'Euclid' (not 'Euclidean') is
#   the official enum name, so out-of-domain spellings must be refused
"""
Attack: behavioral_contract x qdrant_type_collections_create_001 (distance enum
  domain face) (chunk_collections+create-1of2; PUT /collections/{name},
  path_key create_collection from runtime PATHS, URL from raw_knowledge
  api_endpoints[collections+create].url). The assertion (evidence_tier=explicit)
  is a strict enum: vectors.distance IN {Cosine, Euclid, Dot, Manhattan}.
  Positive closure (G4): every one of the four documented members is created
  on a fresh name and must be accepted with 200 result=true AND persist -
  describe readback path result.config.params.vectors.distance (per this
  endpoint family's response_shape, params.vectors:object) must echo the
  member verbatim.
  Negative domain: 'Euclidean' (threat-model by-design note says the official
  name is 'Euclid' - so 'Euclidean' is out-of-domain and must be refused),
  'cosine' (case-sensitive wire value), '' (empty string).
  A documented member refused = Type1_IllegalRejection; an out-of-domain
  spelling accepted = Type1_IllegalSuccess.
  [chunk_collections+create-1of2 coverage: behavioral_contract x
   qdrant_type_collections_create_001 (distance enum closure: 4 members
   accepted + persisted; 3 out-of-domain spellings refused)]
Oracle: all four documented distance members {Cosine, Euclid, Dot, Manhattan}
  create 200 result=true and describe echoes result.config.params.vectors.
  distance == member; 'Euclidean', 'cosine' and '' are refused 400/422 (2xx =
  Type1_IllegalSuccess; refused documented member or non-echoed persistence =
  Type1_IllegalRejection/Type4_StateLogicViolation; 5xx with /healthz alive =
  Type3_RuntimeFailure) - constraint qdrant_type_collections_create_001.

Rationale (G4/G7/G9): enum closure needs both directions; the persistence
readback is checked against the describe response_shape grid so the oracle is
spec-derived, and case-sensitivity is asserted so an inconsistent disposition
across near-identical spellings cannot hide.
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

PREFIX = "scc02_"
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


def describe_params(name):
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
    return params


def expect_create_ok(name, distance):
    """Positive closure: 200 + result=true + persisted distance echo."""
    tag = f"member {distance!r}"
    st, raw = create(name, {"vectors": {"size": 4, "distance": distance}})
    if st == 0:
        liveness("transport")
        script_error(f"transport failure on {tag}; no defect conclusion")
    if 500 <= st <= 599:
        if liveness("5xx") != 200:
            script_error(f"{tag} 5xx ({st}) and /healthz not 200; deployment unstable")
        defect("Type3_RuntimeFailure",
               f"[{tag}] server error {st} while /healthz is alive; a documented enum "
               f"member must create cleanly; raw={str(raw)[:200]}")
    if st != 200:
        defect("Type1_IllegalRejection",
               f"[{tag}] documented Distance enum member refused with {st}; the "
               f"constraint qdrant_type_collections_create_001 declares "
               f"distance IN {{Cosine, Euclid, Dot, Manhattan}}; raw={str(raw)[:250]}")
    b = jload(raw)
    if not isinstance(b, dict) or b.get("result") is not True:
        defect("Type4_StateLogicViolation",
               f"[{tag}] 200 body must carry result=true (response_shape "
               f"result:boolean); raw={str(raw)[:250]}")
    params = describe_params(name)
    vec = params.get("vectors")
    if not isinstance(vec, dict):
        defect("Type4_StateLogicViolation",
               f"[{tag}] describe config.params.vectors is not an object (response_shape "
               f"declares params.vectors:object); got {vec!r}")
    echoed = vec.get("distance")
    print(f"[{tag}] persisted distance echo = {echoed!r}")
    if echoed != distance:
        defect("Type4_StateLogicViolation",
               f"[{tag}] expected result.config.params.vectors.distance == {distance!r}, "
               f"got {echoed!r} (expected vs actual mismatch); raw={str(raw)[:200]}")


def expect_refused(name, distance, why):
    tag = f"invalid {distance!r}"
    st, raw = create(name, {"vectors": {"size": 4, "distance": distance}})
    if st == 0:
        liveness("transport")
        script_error(f"transport failure on {tag}; no defect conclusion")
    if 500 <= st <= 599:
        if liveness("5xx") != 200:
            script_error(f"{tag} 5xx ({st}) and /healthz not 200; deployment unstable")
        defect("Type3_RuntimeFailure",
               f"[{tag}] server error {st} while /healthz is alive; an out-of-domain "
               f"enum value must be refused with a clean 4xx; raw={str(raw)[:200]}")
    if 200 <= st <= 299:
        defect("Type1_IllegalSuccess",
               f"[{tag}] {why} was ACCEPTED with status {st}; distance is a strict enum "
               f"[Cosine, Euclid, Dot, Manhattan] (threat-model by-design note: the "
               f"official spelling is 'Euclid'); raw={str(raw)[:250]}")
    if st in (400, 422):
        print(f"[{tag}] cleanly rejected with {st}")
        return
    script_error(f"[{tag}] unadjudicable refusal status {st} (expected 400/422); "
                 f"raw={str(raw)[:200]}")


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

        for i, d in enumerate(["Cosine", "Euclid", "Dot", "Manhattan"], start=1):
            expect_create_ok(mkn(f"ok{i}_{d.lower()}"), d)

        expect_refused(mkn("bad_euclidean"), "Euclidean",
                       "alias spelling 'Euclidean'")
        expect_refused(mkn("bad_lowercase"), "cosine",
                       "lowercase spelling 'cosine'")
        expect_refused(mkn("bad_empty"), "",
                       "empty-string distance")

        print("[summary] 4/4 documented members accepted and persisted verbatim; "
              "3/3 out-of-domain spellings refused - strict Distance enum domain "
              "holds per qdrant_type_collections_create_001")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
