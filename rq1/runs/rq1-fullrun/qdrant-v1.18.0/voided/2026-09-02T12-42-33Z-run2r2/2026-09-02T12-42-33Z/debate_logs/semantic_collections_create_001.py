#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_create_001
# strategy: type_coercion
# endpoint: collections+create
# constraint_ids: qdrant_type_collections_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust - serde assumed to validate the
#   nested VectorsConfig; the threat model lists "vectors config missing, vectors={},
#   hnsw_config={}" as this endpoint's #1 type_confusion surface)
"""
Attack: type_coercion x qdrant_type_collections_create_001
  (chunk_collections+create-1of2; PUT /collections/{name}, path_key
  create_collection from runtime PATHS, URL from raw_knowledge
  api_endpoints[collections+create].url = /collections/{collection_name}).
  The constraint (evidence_tier=explicit) requires vectors to be a
  VectorParams{size (uint64), distance}; size and distance are required.
  Wrong-typed / missing shapes probed, each on a fresh collection name:
    - vectors omitted entirely (required=true)
    - vectors={} (empty object; VectorParams.required=[size,distance] makes the
      single-config branch unsatisfiable - threat-model BS-01 probe)
    - vectors as list / as string (wrong container type)
    - size as string "4", as float 4.5, as -1 (uint64 violation), as null,
      and omitted
    - distance as integer 2, as null, and omitted
  G4 pairing inside the same script: two legal controls must be accepted -
  plain {size,distance} and hnsw_config={} (HnswConfigDiff all-optional, the
  empty diff is a legal shape; its acceptance proves rejections below are
  about the vectors shape, not about strictness in general).
  [chunk_collections+create-1of2 coverage: type_coercion x
   qdrant_type_collections_create_001 (missing/empty/wrong-typed vectors,
   uint64 + required-field enforcement) + hnsw_config={} legal-diff control]
Oracle: every wrong-typed/missing vectors shape is refused with a clean
  400/422 (any 2xx acceptance = Type1_IllegalSuccess; 5xx with /healthz alive
  = Type3_RuntimeFailure), and both legal controls return 200 with envelope
  result=true (a refused legal control = Type1_IllegalRejection) - asserting
  constraint qdrant_type_collections_create_001 (VectorParams.required =
  [size, distance]; size uint64).

Rationale (G2/G4/G5/G7): the contract fixes the request grammar, so each case
has a spec-derived disposition; controls and attacks share the setup, and every
observed (status, raw) is compared against the declared expectation explicitly
before any verdict.
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

PREFIX = "scc01_"
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


def check_ok_200(st, raw, tag):
    """Accepted-case adjudication: 200 + envelope result:true (response_shape
    declares result:boolean). Returns True iff accepted."""
    if st == 0:
        liveness("transport")
        script_error(f"transport failure on {tag}; no defect conclusion")
    if 500 <= st <= 599:
        if liveness("5xx") != 200:
            script_error(f"{tag} 5xx ({st}) and /healthz not 200; deployment unstable")
        defect("Type3_RuntimeFailure",
               f"[{tag}] server error {st} while /healthz is alive; a legal create must "
               f"succeed, never crash; raw={str(raw)[:200]}")
    if st != 200:
        print(f"[{tag}] expected 200 acceptance, got {st}")
        return False
    b = jload(raw)
    if not isinstance(b, dict) or b.get("result") is not True:
        defect("Type4_StateLogicViolation",
               f"[{tag}] 200 body must carry result=true (collections+create "
               f"response_shape declares result:boolean); raw={str(raw)[:250]}")
    print(f"[{tag}] accepted with 200 and result=true")
    return True


def check_rejected(st, raw, tag, why):
    """Rejected-case adjudication (judge_4xx semantics): 400/422 clean;
    2xx -> Type1_IllegalSuccess; 5xx -> liveness then Type3."""
    if st == 0:
        liveness("transport")
        script_error(f"transport failure on {tag}; no defect conclusion")
    if 500 <= st <= 599:
        if liveness("5xx") != 200:
            script_error(f"{tag} 5xx ({st}) and /healthz not 200; deployment unstable")
        defect("Type3_RuntimeFailure",
               f"[{tag}] server error {st} while /healthz is alive; a malformed "
               f"vectors config must be refused with a clean 4xx, never crash; "
               f"raw={str(raw)[:200]}")
    if 200 <= st <= 299:
        defect("Type1_IllegalSuccess",
               f"[{tag}] {why} was ACCEPTED with status {st} (expected clean 4xx "
               f"rejection per qdrant_type_collections_create_001: VectorParams.requires "
               f"[size, distance], size uint64); raw={str(raw)[:250]}")
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

        # ---- G4 legal controls: must be accepted (else Type1_IllegalRejection) ----
        st, raw = create(mkn("ok_plain"), {"vectors": {"size": 4, "distance": "Cosine"}})
        if not check_ok_200(st, raw, "legal control: plain {size,distance}"):
            defect("Type1_IllegalRejection",
                   f"[legal control] plain vectors={{size: 4, distance: 'Cosine'}} was "
                   f"refused with {st}; VectorParams{{size, distance}} is the documented "
                   f"legal shape (qdrant_type_collections_create_001); raw={str(raw)[:250]}")
        st, raw = create(mkn("ok_empty_hnsw"),
                         {"vectors": {"size": 4, "distance": "Cosine"},
                          "hnsw_config": {}})
        if not check_ok_200(st, raw, "legal control: hnsw_config={} empty diff"):
            defect("Type1_IllegalRejection",
                   f"[legal control] hnsw_config={{}} (HnswConfigDiff all-optional, the "
                   f"empty diff is legal) was refused with {st}; raw={str(raw)[:250]}")

        # ---- attacks: each must be refused with a clean 4xx ----
        cases = [
            ("no_vectors", {}, "vectors omitted entirely (required=true)"),
            ("empty_vectors", {"vectors": {}},
             "vectors={} empty object (VectorParams.requires size+distance)"),
            ("list_vectors", {"vectors": [{"size": 4, "distance": "Cosine"}]},
             "vectors as list (wrong container type)"),
            ("str_vectors", {"vectors": "dense"},
             "vectors as string (wrong container type)"),
            ("size_string", {"vectors": {"size": "4", "distance": "Cosine"}},
             'vectors.size as string "4" (uint64 required)'),
            ("size_float", {"vectors": {"size": 4.5, "distance": "Cosine"}},
             "vectors.size as float 4.5 (uint64 required)"),
            ("size_negative", {"vectors": {"size": -1, "distance": "Cosine"}},
             "vectors.size=-1 (uint64 cannot be negative)"),
            ("size_null", {"vectors": {"size": None, "distance": "Cosine"}},
             "vectors.size=null (required field nulled)"),
            ("size_missing", {"vectors": {"distance": "Cosine"}},
             "vectors.size omitted (required field missing)"),
            ("distance_int", {"vectors": {"size": 4, "distance": 2}},
             "vectors.distance as integer 2 (strict enum required)"),
            ("distance_null", {"vectors": {"size": 4, "distance": None}},
             "vectors.distance=null (required field nulled)"),
            ("distance_missing", {"vectors": {"size": 4}},
             "vectors.distance omitted (required field missing)"),
        ]
        for tag, body, why in cases:
            st, raw = create(mkn(tag), body)
            check_rejected(st, raw, tag, why)

        print("[summary] 2 legal controls accepted (result=true); 12 wrong-typed/missing "
              "vectors shapes all refused with clean 4xx - uint64 + required-field "
              "enforcement holds per qdrant_type_collections_create_001")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
