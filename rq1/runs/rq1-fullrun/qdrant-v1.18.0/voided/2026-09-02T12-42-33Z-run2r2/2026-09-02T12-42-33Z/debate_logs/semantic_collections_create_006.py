#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_create_006
# strategy: behavioral_contract
# endpoint: collections+create
# constraint_ids: qdrant_type_collections_create_005
# source_url: https://qdrant.tech/documentation/manage-data/vectors/
# doc_version: current (site latest; no version archive)
# Blindspot: BS-01 (datatype enum trust on both the dense face and the sparse
#   face; turbo4 is dense-only per the doc contract)
"""
Attack: behavioral_contract x qdrant_type_collections_create_005
  (chunk_collections+create-1of2; PUT /collections/{name}, path_key
  create_collection from runtime PATHS, URL from raw_knowledge
  api_endpoints[collections+create].url). The assertion (evidence_tier=
  explicit): datatype IN {float32, uint8, float16, turbo4}; turbo4 (4-bit) is
  dense-only and cannot be configured for sparse vectors. Probes (fresh name
  each, persistence via describe result.config.params.vectors /
  params.sparse_vectors per the describe response_shape):
    - dense float16 -> 200 + readback params.vectors.datatype == "float16"
      (non-default member chosen so the echo is unambiguous)
    - dense uint8 -> 200 + readback == "uint8"
    - dense float32 -> 200 (readback recorded; default member may be omitted
      by the resolved config - absence is not a defect, only the acceptance
      is the closure claim)
    - dense turbo4 -> dual-acceptable (200 + echo, or a clean 400/422 feature
      refusal on this deployment); never 5xx; if accepted, readback must echo
      "turbo4"
    - dense "float64" -> refused 400/422 (out of enum)
    - dense "FLOAT16" -> refused (case-sensitive wire value)
    - sparse {"sp": {"datatype": "turbo4"}} (+ dense vectors) -> the
      dense-only rule: refused OR accepted-with-drop; DEFECT only if the
      readback persists sparse_vectors.sp.datatype == "turbo4"
  [chunk_collections+create-1of2 coverage: behavioral_contract x
   qdrant_type_collections_create_005 (3 dense closures + turbo4 dual
   disposition + 2 out-of-enum rejections + sparse turbo4 dense-only rule)]
Oracle: float16/uint8/float32 dense creates return 200 result=true and the
  describe echo equals the member when served; turbo4 dense answers 200
  (echo "turbo4") or a clean 400/422; "float64"/"FLOAT16" are refused 400/422
  (2xx = Type1_IllegalSuccess; 5xx with /healthz alive = Type3); the sparse
  turbo4 case never persists sparse_vectors.sp.datatype=="turbo4"
  (persistence = Type1_IllegalSuccess per the dense-only rule) - constraint
  qdrant_type_collections_create_005.

Rationale (G3/G4/G7): turbo4 is new in 1.18 so its dense acceptance is
deployment-conditional (dual-acceptable, measured) while its sparse-face
prohibition is an absolute rule judged on persistence; the float16 closure
uses a non-default member so a silent-default echo cannot mask a defect.
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

PREFIX = "scc06_"
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

        # ---- dense closures: float16, uint8, float32 ----
        for member in ["float16", "uint8", "float32"]:
            name = mkn(f"ok_{member}")
            st, raw = create(name, {"vectors": {"size": 4, "distance": "Cosine",
                                                "datatype": member}})
            guard(st, raw, f"dense {member}")
            if st != 200:
                defect("Type1_IllegalRejection",
                       f"[dense {member}] documented datatype member refused with {st}; "
                       f"constraint qdrant_type_collections_create_005 declares datatype "
                       f"IN {{float32, uint8, float16, turbo4}}; raw={str(raw)[:250]}")
            check_envelope_true(raw, f"dense {member}")
            params = describe_params(name)
            vec = params.get("vectors")
            echoed = vec.get("datatype", "__absent__") if isinstance(vec, dict) else None
            print(f"[dense {member}] persisted datatype echo = {echoed!r}")
            if echoed != "__absent__" and echoed != member:
                defect("Type4_StateLogicViolation",
                       f"[dense {member}] expected params.vectors.datatype == "
                       f"{member!r}, got {echoed!r} (expected vs actual mismatch)")

        # ---- turbo4 dense: dual-acceptable deployment disposition ----
        name = mkn("ok_turbo4")
        st, raw = create(name, {"vectors": {"size": 4, "distance": "Dot",
                                            "datatype": "turbo4"}})
        guard(st, raw, "dense turbo4")
        if st == 200:
            check_envelope_true(raw, "dense turbo4")
            params = describe_params(name)
            vec = params.get("vectors")
            echoed = vec.get("datatype", "__absent__") if isinstance(vec, dict) else None
            print(f"[dense turbo4] accepted; persisted echo = {echoed!r}")
            if echoed not in ("turbo4", "__absent__"):
                defect("Type4_StateLogicViolation",
                       f"[dense turbo4] expected params.vectors.datatype == 'turbo4' "
                       f"or absent, got {echoed!r}")
            print("[dense turbo4] accepted on this deployment (disposition recorded)")
        elif st in (400, 422):
            print(f"[dense turbo4] refused with {st} - clean feature refusal, "
                  f"dual-acceptable disposition recorded; raw={str(raw)[:200]}")
        else:
            script_error(f"[dense turbo4] unadjudicable refusal status {st} "
                         f"(expected 200 or 400/422); raw={str(raw)[:200]}")

        # ---- out-of-enum dense values: each must be refused ----
        for tag, val, why in [
            ("float64", "float64", "out-of-enum member 'float64'"),
            ("upper", "FLOAT16", "case-violating spelling 'FLOAT16'"),
        ]:
            name = mkn(f"bad_{tag}")
            st, raw = create(name, {"vectors": {"size": 4, "distance": "Cosine",
                                                "datatype": val}})
            guard(st, raw, tag)
            if 200 <= st <= 299:
                defect("Type1_IllegalSuccess",
                       f"[{tag}] vectors.datatype={val!r} ({why}) was ACCEPTED with "
                       f"status {st}; the enum is [float32, uint8, float16, turbo4] "
                       f"(qdrant_type_collections_create_005); raw={str(raw)[:250]}")
            if st in (400, 422):
                print(f"[{tag}] cleanly rejected with {st}")
            else:
                script_error(f"[{tag}] unadjudicable refusal status {st} "
                             f"(expected 400/422); raw={str(raw)[:200]}")

        # ---- sparse turbo4: dense-only rule, judged on persistence ----
        name = mkn("sparse_turbo4")
        st, raw = create(name, {"vectors": {"size": 4, "distance": "Cosine"},
                                "sparse_vectors": {"sp": {"datatype": "turbo4"}}})
        guard(st, raw, "sparse turbo4")
        if st == 200:
            check_envelope_true(raw, "sparse turbo4")
            params = describe_params(name)
            sp = params.get("sparse_vectors")
            node = sp.get("sp") if isinstance(sp, dict) else None
            persisted = node.get("datatype") if isinstance(node, dict) else None
            print(f"[sparse turbo4] accepted; persisted sparse sp params = {node!r}")
            if persisted == "turbo4":
                defect("Type1_IllegalSuccess",
                       f"[sparse turbo4] turbo4 configured for a SPARSE vector and "
                       f"persisted (sparse_vectors.sp.datatype=='turbo4' in the "
                       f"describe readback); constraint qdrant_type_collections_create_"
                       f"005: turbo4 is dense-only and cannot be configured for sparse "
                       f"vectors")
            print("[sparse turbo4] accepted with the field dropped/normalized - "
                  "dense-only rule holds via drop")
        elif st in (400, 422):
            print(f"[sparse turbo4] refused with {st} - dense-only rule holds "
                  f"via rejection")
        else:
            script_error(f"[sparse turbo4] unadjudicable refusal status {st} "
                         f"(expected 200 or 400/422); raw={str(raw)[:200]}")

        print("[summary] float16/uint8/float32 closures accepted (+echo when "
              "served); turbo4 dual-disposition recorded; float64/FLOAT16 "
              "refused; sparse turbo4 never persisted - datatype domain and "
              "dense-only rule hold per qdrant_type_collections_create_005")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
