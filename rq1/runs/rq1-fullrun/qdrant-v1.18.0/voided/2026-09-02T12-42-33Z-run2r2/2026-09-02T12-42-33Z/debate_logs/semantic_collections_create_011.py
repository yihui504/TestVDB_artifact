#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_create_011
# strategy: behavioral_contract
# endpoint: collections+create
# constraint_ids: qdrant_range_collections_create_003
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (closed-interval boundary: BOTH endpoints 0.5 and 1.0 are
#   legal - G4 boundary closure) + BS-02 (refusal diagnostics for
#   just-outside quantiles)
"""
Attack: behavioral_contract + diagnosis_quality x
  qdrant_range_collections_create_003 (chunk_collections+create-1of2;
  PUT /collections/{name}, path_key create_collection from runtime PATHS,
  URL from raw_knowledge api_endpoints[collections+create].url). The
  assertion (evidence_tier=explicit): ScalarQuantization quantile must lie in
  the CLOSED interval [0.5, 1.0]. Probes (fresh name each, scalar
  quantization config with int8 type held constant; persistence via describe
  result.config.quantization_config.scalar per the describe response_shape):
    - quantile=0.5 -> closed-interval lower endpoint: accepted 200 + echo 0.5
    - quantile=1.0 -> closed-interval upper endpoint: accepted 200 + echo 1.0
    - quantile=0.49 -> just below: refused 400/422 (Type-2 rubric scored)
    - quantile=1.01 -> just above: refused 400/422
  [chunk_collections+create-1of2 coverage: behavioral_contract x
   qdrant_range_collections_create_003 (both closed-interval endpoints
   accepted + persisted) + diagnosis_quality x
   qdrant_range_collections_create_003 (0.49/1.01 refusal rubric)]
Oracle: quantile=0.5 and quantile=1.0 each create 200 result=true and
  describe echoes quantization_config.scalar.quantile == the endpoint value
  (within 1e-9; refusal of an endpoint = Type1_IllegalRejection; echo
  mismatch = Type4); quantile=0.49 and 1.01 are refused 400/422 (any 2xx =
  Type1_IllegalSuccess; 5xx with /healthz alive = Type3) and neither refusal
  scores 0/3 on the Type-2 rubric (0/3 = Type2_PoorDiagnostics) - constraint
  qdrant_range_collections_create_003.

Rationale (G4/G5/G7): a closed interval is only falsified by probing its own
endpoints (inclusive) against immediate outsiders (exclusive); the float echo
uses a tolerance so binary representation noise cannot fake a mismatch, and
the refusals are rubric-scored so nameless rejections surface.
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

PREFIX = "scc11_"
RUN = str(int(time.time()))
CREATED = []
DENSE = {"size": 4, "distance": "Cosine"}
EPS = 1e-9


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


def create(name, quantile):
    body = {"vectors": DENSE,
            "quantization_config": {"scalar": {"type": "int8",
                                               "quantile": quantile}}}
    st, raw = safe_request("PUT", "create_collection", body, path_params={"name": name})
    print(f"[create {name} quantile={quantile}] status={st} raw={str(raw)[:300]}")
    if st in (200, 201):
        CREATED.append(name)
    return st, raw


def describe_scalar(name):
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
    q = cfg.get("quantization_config")
    node = q.get("scalar") if isinstance(q, dict) else None
    if not isinstance(node, dict):
        script_error(f"describe of {name} returned no quantization_config.scalar "
                     f"(response_shape declares result.config.quantization_config.scalar:"
                     f"object): raw={str(raw)[:200]}")
    return node


def check_error_quality(raw, expected_param):
    """Type-2 rubric: parameter_named + format_hint + actionable."""
    body = jload(raw) if isinstance(raw, str) else raw
    error_msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()
    score = 0
    criteria = []
    if expected_param.lower() in error_msg:
        score += 1
        criteria.append("param_named")
    format_hints = ["must be", "expected", "should be", "valid", "range", "type",
                    "at least", "minimum", "maximum", "between", "greater", "less"]
    hit = [h for h in format_hints if h in error_msg]
    if hit:
        score += 1
        criteria.append(f"format_hint({hit[0]})")
    action_hints = ["correct", "try", "use", "change", "specify", "provide"]
    hit2 = [h for h in action_hints if h in error_msg]
    if hit2:
        score += 1
        criteria.append(f"actionable({hit2[0]})")
    return score, criteria, error_msg


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

        # ---- closed-interval endpoints: both must be accepted + echoed ----
        for endpoint in [0.5, 1.0]:
            tag = f"quantile {endpoint}"
            name = mkn(f"ok_q{str(endpoint).replace('.', '_')}")
            st, raw = create(name, endpoint)
            guard(st, raw, tag)
            if st != 200:
                defect("Type1_IllegalRejection",
                       f"[{tag}] the CLOSED interval [0.5, 1.0] includes its endpoints; "
                       f"refused with {st}; constraint qdrant_range_collections_create_003; "
                       f"raw={str(raw)[:250]}")
            b = jload(raw)
            if not isinstance(b, dict) or b.get("result") is not True:
                defect("Type4_StateLogicViolation",
                       f"[{tag}] 200 body must carry result=true (response_shape "
                       f"result:boolean); raw={str(raw)[:250]}")
            node = describe_scalar(name)
            echoed = node.get("quantile")
            print(f"[{tag}] persisted scalar.quantile echo = {echoed!r}")
            if not isinstance(echoed, (int, float)) or isinstance(echoed, bool) \
                    or abs(float(echoed) - endpoint) > EPS:
                defect("Type4_StateLogicViolation",
                       f"[{tag}] expected quantization_config.scalar.quantile == "
                       f"{endpoint} (tolerance 1e-9), got {echoed!r} (expected vs "
                       f"actual mismatch)")

        # ---- just-outside values: each must be refused + rubric-scored ----
        for outside, why in [(0.49, "just below the 0.5 lower endpoint"),
                             (1.01, "just above the 1.0 upper endpoint")]:
            tag = f"quantile {outside}"
            name = mkn(f"bad_q{str(outside).replace('.', '_')}")
            st, raw = create(name, outside)
            guard(st, raw, tag)
            if 200 <= st <= 299:
                defect("Type1_IllegalSuccess",
                       f"[{tag}] quantile={outside} ({why}) was ACCEPTED with status "
                       f"{st}; constraint qdrant_range_collections_create_003 fixes "
                       f"the closed interval [0.5, 1.0]; raw={str(raw)[:250]}")
            if st not in (400, 422):
                script_error(f"[{tag}] unadjudicable refusal status {st} "
                             f"(expected 400/422); raw={str(raw)[:200]}")
            score, criteria, msg = check_error_quality(raw, "quantile")
            print(f"[{tag}] refused with {st}; rubric score={score}/3 "
                  f"criteria={criteria}; message={msg[:250]}")
            if score == 0:
                defect("Type2_PoorDiagnostics",
                       f"[{tag}] the refusal for quantile={outside} ({why}) names no "
                       f"parameter, gives no range hint and no actionable suggestion "
                       f"(0/3 on the Type-2 rubric); message={msg[:250]}")

        print("[summary] closed-interval endpoints 0.5 and 1.0 accepted + echoed; "
              "0.49 and 1.01 refused with rubric-carrying diagnostics - quantile "
              "range promise holds per qdrant_range_collections_create_003")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
