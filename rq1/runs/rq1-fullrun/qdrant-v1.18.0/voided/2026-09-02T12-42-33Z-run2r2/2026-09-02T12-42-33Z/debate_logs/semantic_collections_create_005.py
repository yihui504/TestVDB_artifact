#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_create_005
# strategy: behavioral_contract
# endpoint: collections+create
# constraint_ids: qdrant_type_collections_create_004
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (nested quantization enum trust: scalar.type /
#   product.compression / binary.encoding sub-enum domains assumed validated)
"""
Attack: behavioral_contract x qdrant_type_collections_create_004
  (chunk_collections+create-1of2; PUT /collections/{name}, path_key
  create_collection from runtime PATHS, URL from raw_knowledge
  api_endpoints[collections+create].url). The assertion (evidence_tier=
  explicit) fixes the quantization_config type domain: ScalarQuantization.type
  = int8; ProductQuantization.compression IN {x4, x8, x16, x32, x64};
  BinaryQuantization.encoding IN {one_bit, two_bits, one_and_half_bits}; null
  disables quantization. Probes (each on a fresh name, persistence readback
  via describe result.config.quantization_config, response_shape: any with
  scalar/product/binary object subkeys):
    - scalar {"type": "int8", "quantile": 0.8} -> 200 + readback
      quantization_config.scalar.type == "int8" (quantile held constant at a
      legal 0.8 here; its range is range_collections_create_003's business)
    - scalar {"type": "int16"} -> refused 400/422 (out of the int8-only domain)
    - scalar branch without "type" -> refused (request_required_paths lists
      quantization_config.scalar.type as required in the scalar branch)
    - product {"compression": "x4"} -> 200 + readback compression == "x4"
    - product {"compression": "x5"} -> refused (not in the enum)
    - binary {"encoding": "one_bit"} -> 200 + readback encoding == "one_bit"
      when served
    - binary {"encoding": "three_bits"} -> refused (not in the enum)
    - quantization_config null -> 200 with no quantization in the readback
  [chunk_collections+create-1of2 coverage: behavioral_contract x
   qdrant_type_collections_create_004 (scalar/product/binary enum closure +
   3 out-of-domain values + required scalar.type + null-disables)]
Oracle: scalar int8 / product x4 / binary one_bit creates all return 200
  result=true and persist their enum value in
  result.config.quantization_config (mismatched echo = Type4); int16 / x5 /
  three_bits / type-less scalar are refused 400/422 (any 2xx =
  Type1_IllegalSuccess; refused documented value = Type1_IllegalRejection;
  5xx with /healthz alive = Type3_RuntimeFailure); null leaves no
  quantization_config in the readback - constraint
  qdrant_type_collections_create_004.

Rationale (G4/G7): each sub-enum gets a documented-member closure probe AND an
out-of-domain probe so neither direction of the domain claim goes untested;
persistence echoes are checked against the describe shape grid (scalar/
product/binary object subkeys) rather than assumed.
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

PREFIX = "scc05_"
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


def describe_quantization(name):
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
    return cfg.get("quantization_config", "__absent__")


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

        # ---- scalar int8 closure ----
        name = mkn("ok_scalar")
        st, raw = create(name, {"vectors": DENSE,
                                "quantization_config": {"scalar": {"type": "int8",
                                                                   "quantile": 0.8}}})
        guard(st, raw, "scalar int8")
        if st != 200:
            defect("Type1_IllegalRejection",
                   f"[scalar int8] documented scalar type 'int8' refused with {st}; "
                   f"constraint qdrant_type_collections_create_004 declares "
                   f"ScalarQuantization.type = int8; raw={str(raw)[:250]}")
        check_envelope_true(raw, "scalar int8")
        q = describe_quantization(name)
        print(f"[scalar int8] persisted quantization_config = {str(q)[:200]}")
        node = q.get("scalar") if isinstance(q, dict) else None
        if not isinstance(node, dict) or node.get("type") != "int8":
            defect("Type4_StateLogicViolation",
                   f"[scalar int8] expected result.config.quantization_config.scalar.type "
                   f"== 'int8', got {node!r} (expected vs actual mismatch)")

        # ---- product x4 closure ----
        name = mkn("ok_product")
        st, raw = create(name, {"vectors": DENSE,
                                 "quantization_config": {"product": {"compression": "x4"}}})
        guard(st, raw, "product x4")
        if st != 200:
            defect("Type1_IllegalRejection",
                   f"[product x4] documented compression 'x4' refused with {st}; "
                   f"enum is [x4, x8, x16, x32, x64]; raw={str(raw)[:250]}")
        check_envelope_true(raw, "product x4")
        q = describe_quantization(name)
        print(f"[product x4] persisted quantization_config = {str(q)[:200]}")
        node = q.get("product") if isinstance(q, dict) else None
        if not isinstance(node, dict) or node.get("compression") != "x4":
            defect("Type4_StateLogicViolation",
                   f"[product x4] expected result.config.quantization_config.product."
                   f"compression == 'x4', got {node!r}")

        # ---- binary one_bit closure ----
        name = mkn("ok_binary")
        st, raw = create(name, {"vectors": DENSE,
                                 "quantization_config": {"binary": {"encoding": "one_bit"}}})
        guard(st, raw, "binary one_bit")
        if st != 200:
            defect("Type1_IllegalRejection",
                   f"[binary one_bit] documented encoding 'one_bit' refused with {st}; "
                   f"encoding enum is [one_bit, two_bits, one_and_half_bits]; "
                   f"raw={str(raw)[:250]}")
        check_envelope_true(raw, "binary one_bit")
        q = describe_quantization(name)
        print(f"[binary one_bit] persisted quantization_config = {str(q)[:200]}")
        node = q.get("binary") if isinstance(q, dict) else None
        if isinstance(node, dict):
            enc = node.get("encoding", "__absent__")
            if enc != "__absent__" and enc != "one_bit":
                defect("Type4_StateLogicViolation",
                       f"[binary one_bit] expected binary.encoding == 'one_bit', "
                       f"got {enc!r}")
            print(f"[binary one_bit] encoding echo = {enc!r}")

        # ---- null disables ----
        name = mkn("ok_null")
        st, raw = create(name, {"vectors": DENSE, "quantization_config": None})
        guard(st, raw, "null disables")
        if st != 200:
            defect("Type1_IllegalRejection",
                   f"[null disables] quantization_config=null (documented 'null disables "
                   f"quantization') refused with {st}; raw={str(raw)[:250]}")
        check_envelope_true(raw, "null disables")
        q = describe_quantization(name)
        print(f"[null disables] readback quantization_config = {q!r}")
        if q not in (None, "__absent__"):
            defect("Type4_StateLogicViolation",
                   f"[null disables] quantization_config=null must leave no "
                   f"quantization config in the describe readback; got {str(q)[:200]}")

        # ---- out-of-domain / required-missing: each must be refused ----
        cases = [
            ("int16", {"scalar": {"type": "int16", "quantile": 0.8}},
             "scalar type 'int16' (domain is int8 only)"),
            ("no_scalar_type", {"scalar": {"quantile": 0.8}},
             "scalar branch without required 'type' (request_required_paths: "
             "quantization_config.scalar.type)"),
            ("x5", {"product": {"compression": "x5"}},
             "product compression 'x5' (enum is x4/x8/x16/x32/x64)"),
            ("three_bits", {"binary": {"encoding": "three_bits"}},
             "binary encoding 'three_bits' (enum is one_bit/two_bits/one_and_half_bits)"),
        ]
        for tag, qc, why in cases:
            name = mkn(f"bad_{tag}")
            st, raw = create(name, {"vectors": DENSE, "quantization_config": qc})
            guard(st, raw, tag)
            if 200 <= st <= 299:
                defect("Type1_IllegalSuccess",
                       f"[{tag}] quantization_config={qc} ({why}) was ACCEPTED with "
                       f"status {st}; constraint qdrant_type_collections_create_004 "
                       f"fixes the type domain; raw={str(raw)[:250]}")
            if st in (400, 422):
                print(f"[{tag}] cleanly rejected with {st}")
            else:
                script_error(f"[{tag}] unadjudicable refusal status {st} "
                             f"(expected 400/422); raw={str(raw)[:200]}")

        print("[summary] int8/x4/one_bit closures accepted + persisted; null "
              "disabled cleanly; int16/type-less/x5/three_bits all refused - "
              "quantization type domain holds per qdrant_type_collections_create_004")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
