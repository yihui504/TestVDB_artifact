#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_update_004
# strategy: behavioral_contract
# endpoint: collections+update
# constraint_ids: qdrant_state_collections_update_001
# source_url: https://qdrant.tech/documentation/manage-data/collections/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-05 (Documentation Drift - the manage-data/collections page
#   promises "you can not change the size or distance of an existing vector"
#   while "changing index, quantization or disk parameters is possible"; the
#   PATCH face's TRUE semantics - whether the immutable side is refused or
#   silently accepted-without-echo, and whether the changeable side actually
#   echoes - are verified here against the live runtime via describe readback,
#   not by trusting the 200 status code; R16 standing lesson: PATCH update
#   semantics must be probed via describe readback because 200-without-echo
#   = silent ignore)
"""
Attack: behavioral_contract (S1) x qdrant_state_collections_update_001 on
  collections+update (chunk_collections+update unit
  constraints::qdrant_state_collections_update_001 - system level, empty
  binding -> general testing principles both-direction construction (D2/G4):
  positive = a legal request exercising the changeable promise, negative = a
  construction violating the immutability promise. assertion: "after creation,
  size/distance of an existing (named) vector cannot be changed via PATCH
  update; index/quantization/disk config can", evidence_tier=explicit,
  source https://qdrant.tech/documentation/manage-data/collections/ (the
  manage-data/collections prose). The claim side is STATE-BASED: every PATCH
  outcome is verified through the describe readback of the vector-space
  definition, never through the response status alone (R16: 200-without-echo
  silent-ignore family).
  R17 semantic reconciliation (G10): qdrant_state_collections_update_001 is
  owned here (_004). The response-status face of the same endpoint (200/404/
  400-on-invalid-diff) is owned by semantic_collections_update_001 on the
  behavioral unit. search_correctness/metamorphic/filter_semantics have no
  applicable surface on the config-update face (honest report, G10); the
  post-change search leg below is a healthy-after-patch sanity control, not
  a ranking claim.
Oracle: a PATCH attempting to alter the size or the distance of an existing
  named vector NEVER changes the describe-readback vector-space definition:
  result.config.params.vectors.img.size stays 4 and .distance stays "Dot"
  after each attempt (any readback change of size or distance =
  Type4_StateLogicViolation - the documented immutability promise is broken);
  the attempt's HTTP status is measured and recorded (4xx refusal = clean
  enforcement; 200-without-echo = compliant for THIS unit's promise but
  recorded as false-success evidence for the behavioral unit's invalid-diff
  claim - cross-unit note, not claimed here); a PATCH addressing a vector
  NAME that does not exist is refused 4xx (any 2xx on an unaddressable name =
  Type1_IllegalSuccess; measured v1.18.0 sibling behavior answers 400 "Wrong
  input: Not existing vector name error"); the changeable side of the
  assertion holds: PATCH hnsw_config {ef_construct: 64} returns 200 AND the
  describe readback config.hnsw_config.ef_construct == 64 (200-without-echo
  on the changeable side = Type4_StateLogicViolation silent-ignore, run2r #1
  inline_storage defect family - the "index config CAN change" half of the
  assertion requires the change to land); the collection then accepts a
  wait=true upsert of 3 dim-4 points and a search returns 3 hits (healthy
  after patch, no crash/5xx wreckage - 5xx with healthy /healthz =
  Type3_RuntimeFailure); setup/transport failures never produce defect
  conclusions (G8).

Constraint anchor qdrant_state_collections_update_001 (explicit, system):
  description: "1.18 allows changing index/quantization/disk configuration
  post-create through update; vector-space-defining properties (size/distance
  of an existing named vector) cannot be altered through update [DOC
  collections]"
  assertion: "after creation, size/distance of an existing (named) vector
  cannot be changed via PATCH update; index/quantization/disk config can"

Schema cross-check (versioned v-1-18-x OpenAPI, spec wins): VectorParamsDiff
  members are hnsw_config / quantization_config / on_disk / memory only -
  size and distance are NOT members, so a diff carrying them is
  schema-invalid on the update face and can never lawfully land; the
  immutability assertion is therefore ALSO spec-derived.
"""
import os
import sys
import json
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

PFX = "scu04" + uuid.uuid4().hex[:6]
COL = PFX + "_named"
VNAME = "img"
SIZE = 4
DIST = "Dot"


def safe_request(method, path_key, body=None, path_params=None, query_params=None,
                 timeout=30):
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


def transport_guard(label, st, raw):
    if st <= 0 or 500 <= st <= 599:
        hs = liveness(label)
        if hs != 200:
            defect("Type3_RuntimeFailure",
                   f"service down - '{label}' got status={st} and /healthz={hs}")
        if st <= 0:
            script_error(f"transport failure '{label}' with healthy /healthz: {str(raw)[:150]}")
        defect("Type3_RuntimeFailure",
               f"'{label}' got {st} with /healthz alive; raw={str(raw)[:250]}")
    return st


def vector_meta(name, vecname):
    """describe -> result.config.params.vectors.<vecname> as (size, distance,
    status, err). Named-map readback: params.vectors = {<name>: {size,
    distance, ...}} per the collections+get response_shape grid."""
    st, raw = safe_request("GET", "describe_collection", path_params={"name": name},
                           timeout=30)
    if st != 200:
        return None, None, st, f"describe failed: st={st} raw={str(raw)[:200]}"
    body = jload(raw)
    res = body.get("result") if isinstance(body, dict) else None
    params = ((res or {}).get("config") or {}).get("params") if isinstance(res, dict) else None
    vecs = (params or {}).get("vectors") if isinstance(params, dict) else None
    node = None
    if isinstance(vecs, dict) and vecname in vecs and isinstance(vecs[vecname], dict):
        node = vecs[vecname]
    elif isinstance(vecs, dict) and "size" in vecs:
        # unnamed single-vector representation (should not happen for named)
        node = vecs
    if not isinstance(node, dict):
        return None, None, st, f"params.vectors.{vecname} node missing: {str(vecs)[:300]}"
    return node.get("size"), node.get("distance"), st, None


def hnsw_ef(name):
    st, raw = safe_request("GET", "describe_collection", path_params={"name": name},
                           timeout=30)
    if st != 200:
        return None, f"describe failed: st={st} raw={str(raw)[:200]}"
    body = jload(raw)
    res = body.get("result") if isinstance(body, dict) else None
    hnsw = ((res or {}).get("config") or {}).get("hnsw_config") if isinstance(res, dict) else None
    if not isinstance(hnsw, dict):
        return None, f"config.hnsw_config missing: {str(res)}"[:300]
    return hnsw.get("ef_construct"), None


def cleanup():
    try:
        rt.drop_collection(COL)
    except Exception as e:
        print(f"cleanup warning (drop {COL}): {e}")


def main():
    print(f"ownership prefix: {PFX}")
    print("[assertion quote] 'after creation, size/distance of an existing "
          "(named) vector cannot be changed via PATCH update; "
          "index/quantization/disk config can'")
    try:
        # ---- setup: named-vector collection created manually ----
        st, raw = safe_request("PUT", "create_collection",
                               body={"vectors": {VNAME: {"size": SIZE, "distance": DIST}}},
                               path_params={"name": COL}, timeout=30)
        print(f"[setup create {COL}] status={st} raw={str(raw)[:300]}")
        transport_guard("setup create", st, raw)
        if st not in (200, 201):
            script_error(f"premise create {COL} failed: {st} {str(raw)[:200]}")
        size, dist, st, err = vector_meta(COL, VNAME)
        if err:
            script_error(f"setup baseline readback failed: {err}")
        print(f"[baseline] vectors.{VNAME} = size={size} distance={dist}")
        if size != SIZE or dist != DIST:
            script_error(f"baseline mismatch: expected size={SIZE} distance={DIST}, "
                         f"got size={size} distance={dist}")

        # ---- leg 1: size-alteration attempt must never land (negative) ----
        st, raw = safe_request("PATCH", "update_collection",
                               body={"vectors": {VNAME: {"size": 128}}},
                               path_params={"name": COL}, timeout=30)
        print(f"[leg1 PATCH vectors.{VNAME}.size=128] status={st} raw={str(raw)[:300]}")
        transport_guard("leg1 size attempt", st, raw)
        size, dist, _, err = vector_meta(COL, VNAME)
        if err:
            script_error(f"leg1 readback failed: {err}")
        print(f"[leg1 readback] vectors.{VNAME} = size={size} distance={dist}")
        if size != SIZE or dist != DIST:
            defect("Type4_StateLogicViolation",
                   f"size-alteration PATCH changed the vector space: sent "
                   f"size=128, describe now reads size={size} distance={dist}; "
                   f"the assertion 'size/distance of an existing (named) vector "
                   f"cannot be changed via PATCH update' is broken")
        if 200 <= st < 300:
            print(f"[leg1 note] size attempt answered {st} result-ok with NO "
                  f"readback change - 200-without-echo silent-ignore (state unit "
                  f"promise satisfied); recorded as false-success evidence for "
                  f"the behavioral unit's invalid-diff-4xx claim "
                  f"(semantic_collections_update_001) - not claimed here")
        elif st in (400, 422):
            print(f"[leg1 note] size attempt refused {st} - immutability "
                  f"enforced by rejection")

        # ---- leg 2: distance-alteration attempt must never land (negative) ----
        st, raw = safe_request("PATCH", "update_collection",
                               body={"vectors": {VNAME: {"distance": "Cosine"}}},
                               path_params={"name": COL}, timeout=30)
        print(f"[leg2 PATCH vectors.{VNAME}.distance=Cosine] status={st} raw={str(raw)[:300]}")
        transport_guard("leg2 distance attempt", st, raw)
        size, dist, _, err = vector_meta(COL, VNAME)
        if err:
            script_error(f"leg2 readback failed: {err}")
        print(f"[leg2 readback] vectors.{VNAME} = size={size} distance={dist}")
        if size != SIZE or dist != DIST:
            defect("Type4_StateLogicViolation",
                   f"distance-alteration PATCH changed the vector space: sent "
                   f"distance=Cosine, describe now reads size={size} "
                   f"distance={dist}; the immutability assertion is broken")
        if 200 <= st < 300:
            print(f"[leg2 note] distance attempt answered {st} result-ok with NO "
                  f"readback change - false-success evidence recorded (see leg1 "
                  f"note), not claimed on this unit")
        elif st in (400, 422):
            print(f"[leg2 note] distance attempt refused {st} - immutability "
                  f"enforced by rejection")

        # ---- leg 3: nonexistent vector NAME in the diff (negative control) ----
        st, raw = safe_request("PATCH", "update_collection",
                               body={"vectors": {"nosuchvec": {"hnsw_config": {"m": 8}}}},
                               path_params={"name": COL}, timeout=30)
        print(f"[leg3 PATCH vectors.nosuchvec.hnsw_config] status={st} raw={str(raw)[:300]}")
        transport_guard("leg3 unknown vector name", st, raw)
        if 200 <= st < 300:
            defect("Type1_IllegalSuccess",
                   f"PATCH addressing vector name 'nosuchvec' (does not exist on "
                   f"{COL}) answered HTTP {st} with result-ok; a diff cannot "
                   f"lawfully address a nonexistent vector (measured v1.18.0 "
                   f"sibling behavior refuses with 400 'Not existing vector "
                   f"name error') - phantom success: {str(raw)[:300]!r}")
        if st not in (400, 422):
            defect("Type4_StateLogicViolation",
                   f"unknown-vector-name diff answered HTTP {st}; expected a "
                   f"4xx client error: {str(raw)[:300]!r}")
        print(f"[leg3] unknown vector name refused {st} - OK")

        # ---- leg 4: changeable side - hnsw index config CAN change and echo ----
        st, raw = safe_request("PATCH", "update_collection",
                               body={"hnsw_config": {"ef_construct": 64}},
                               path_params={"name": COL}, timeout=30)
        print(f"[leg4 PATCH hnsw_config.ef_construct=64] status={st} raw={str(raw)[:300]}")
        transport_guard("leg4 hnsw patch", st, raw)
        if st != 200:
            defect("Type1_IllegalRejection",
                   f"legal index-config PATCH (hnsw_config.ef_construct=64, "
                   f"inside the documented HnswConfigDiff range) answered HTTP "
                   f"{st}; the assertion's changeable half promises index "
                   f"config CAN be changed via update: {str(raw)[:300]!r}")
        ef, err = hnsw_ef(COL)
        if err:
            script_error(f"leg4 echo readback failed: {err}")
        print(f"[leg4 echo] describe hnsw_config.ef_construct={ef} (sent 64)")
        if ef != 64:
            defect("Type4_StateLogicViolation",
                   f"changeable-side PATCH answered 200 result:true but describe "
                   f"echoes hnsw_config.ef_construct={ef} (sent 64) - "
                   f"200-without-echo silent-ignore (run2r #1 inline_storage "
                   f"defect family); the assertion's 'index config can change' "
                   f"half requires the change to land")

        # ---- leg 5: healthy-after-patch sanity (upsert + search) ----
        pts = [
            {"id": 1, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"t": "a"}},
            {"id": 2, "vector": [0.9, 0.0, 0.0, 0.0], "payload": {"t": "b"}},
            {"id": 3, "vector": [0.0, 0.9, 0.0, 0.0], "payload": {"t": "c"}},
        ]
        st, raw = safe_request("PUT", "upsert_points", body={"points": pts},
                               path_params={"name": COL},
                               query_params={"wait": "true"}, timeout=60)
        print(f"[leg5 upsert] status={st} raw={str(raw)[:200]}")
        transport_guard("leg5 upsert", st, raw)
        if st not in (200, 201):
            script_error(f"post-patch upsert failed: {st} {str(raw)[:200]}")
        st, raw = safe_request("POST", "search",
                               body={"vector": [0.1, 0.2, 0.3, 0.4], "limit": 3,
                                     "with_payload": False},
                               path_params={"name": COL}, timeout=30)
        print(f"[leg5 search] status={st} raw={str(raw)[:400]}")
        transport_guard("leg5 search", st, raw)
        if st != 200:
            defect("Type3_RuntimeFailure",
                   f"search on {COL} after the config PATCHes answered {st} - "
                   f"collection left unhealthy by the update face: {str(raw)[:300]!r}")
        body = jload(raw)
        hits = body.get("result") if isinstance(body, dict) else None
        if not isinstance(hits, list) or len(hits) != 3:
            defect("Type4_StateLogicViolation",
                   f"post-patch search returned {len(hits) if isinstance(hits, list) else hits} "
                   f"hits for 3 upserted points (expected 3): {str(raw)[:300]!r}")
        print("[leg5] upsert + search healthy (3/3 hits) after the config PATCHes")

        print(f"OK: vector-space immutability held through size/distance "
              f"alteration attempts (readback size={SIZE} distance={DIST} "
              f"stable); unknown vector name refused 4xx; changeable side "
              f"echoed (ef_construct=64); collection healthy afterwards")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
