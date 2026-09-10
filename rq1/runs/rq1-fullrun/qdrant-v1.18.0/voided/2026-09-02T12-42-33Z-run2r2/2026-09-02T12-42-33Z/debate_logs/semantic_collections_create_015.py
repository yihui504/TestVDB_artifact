#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_create_015
# strategy: behavioral_contract
# endpoint: collections+create
# constraint_ids: qdrant_range_collections_create_006
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (closed interval [1, 100] on a deprecated-but-live field)
#   + BS-02 (refusal diagnostics); deprecation (removal scheduled 1.21,
#   superseded by PUT /quotas) makes the in-range disposition
#   deployment-conditional - measured dual-acceptable - while the
#   out-of-range PERSISTENCE claim stays hard
"""
Attack: behavioral_contract + diagnosis_quality x
  qdrant_range_collections_create_006 (chunk_collections+create-1of2;
  PUT /collections/{name}, path_key create_collection from runtime PATHS,
  URL from raw_knowledge api_endpoints[collections+create].url). The
  assertion (evidence_tier=explicit): strict_mode_config.
  max_resident_memory_percent is bounded to the closed interval [1, 100]
  when set; deprecated in 1.18 (removal 1.21). Probes (fresh names;
  readback via describe result.config.strict_mode_config.
  max_resident_memory_percent, response_shape: integer|null):
    - in-range 1 -> accepted-and-persisted (echo 1) OR cleanly refused 4xx
      (deprecation guard) - dual acceptable, never 5xx
    - in-range 100 (upper endpoint) -> same dual disposition
    - out-of-range 0 and 101 -> the hard claim: refused 4xx, or if accepted
      then NOT persisted (silent drop); persistence of 0/101 breaks the
      [1,100] bound in state
  The 0-case refusal message is scored on the Type-2 rubric.
  [chunk_collections+create-1of2 coverage: behavioral_contract x
   qdrant_range_collections_create_006 (1/100 dual-disposition closures +
   0/101 never-persisted) + diagnosis_quality x
   qdrant_range_collections_create_006 (0-case refusal rubric)]
Oracle: max_resident_memory_percent=1 and =100 each answer 200 result=true
  with an echo equal to the value, or a clean 400/422 (5xx with /healthz
  alive = Type3_RuntimeFailure; any other status = SCRIPT_ERROR);
  =0 and =101 are refused 4xx or accepted-but-not-persisted - a persisted
  0/101 in result.config.strict_mode_config.max_resident_memory_percent is
  Type4_StateLogicViolation, and a 2xx acceptance whose 0/101 value also
  persists is additionally Type1_IllegalSuccess - constraint
  qdrant_range_collections_create_006.

Rationale (G3/G5/G7): deprecation makes the in-range acceptance
deployment-conditional (dual-acceptable per the threat-model avoidance
discipline), so the falsifiable core is the out-of-range persistence claim;
adjudication mirrors the canonical schema-attack matrix (refuse or drop =
compliant, persist = defect) instead of demanding a single disposition.
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

PREFIX = "scc15_"
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


def create(name, percent):
    st, raw = safe_request("PUT", "create_collection",
                           {"vectors": DENSE,
                            "strict_mode_config": {
                                "max_resident_memory_percent": percent}},
                           path_params={"name": name})
    print(f"[create {name} mrmp={percent}] status={st} raw={str(raw)[:300]}")
    if st in (200, 201):
        CREATED.append(name)
    return st, raw


def describe_mrmp(name):
    """Readback per response_shape:
    result.config.strict_mode_config.max_resident_memory_percent (int|null)."""
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
    sm = cfg.get("strict_mode_config")
    if not isinstance(sm, dict):
        print(f"[describe {name}] config.strict_mode_config absent in readback "
              f"(measured: field not served); raw={str(raw)[:200]}")
        return "__absent__"
    return sm.get("max_resident_memory_percent", "__absent__")


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

        # ---- in-range endpoints 1 and 100: dual-acceptable disposition ----
        for inrange in [1, 100]:
            tag = f"mrmp {inrange}"
            name = mkn(f"ok_{inrange}")
            st, raw = create(name, inrange)
            guard(st, raw, tag)
            if st == 200:
                b = jload(raw)
                if not isinstance(b, dict) or b.get("result") is not True:
                    defect("Type4_StateLogicViolation",
                           f"[{tag}] 200 body must carry result=true (response_shape "
                           f"result:boolean); raw={str(raw)[:250]}")
                echoed = describe_mrmp(name)
                print(f"[{tag}] accepted; readback mrmp = {echoed!r}")
                if echoed not in (inrange, "__absent__"):
                    defect("Type4_StateLogicViolation",
                           f"[{tag}] expected strict_mode_config."
                           f"max_resident_memory_percent == {inrange} (or absent), "
                           f"got {echoed!r}")
                print(f"[{tag}] in-range disposition: accepted (deprecated field "
                      f"still honored on this deployment; recorded)")
            elif st in (400, 422):
                print(f"[{tag}] in-range disposition: refused with {st} "
                      f"(deprecation guard acceptable; dual-acceptable recorded); "
                      f"raw={str(raw)[:200]}")
            else:
                script_error(f"[{tag}] unadjudicable status {st} (expected 200 or "
                             f"400/422); raw={str(raw)[:200]}")

        # ---- out-of-range 0 and 101: refuse-or-drop, never persist ----
        for out in [0, 101]:
            tag = f"mrmp {out}"
            name = mkn(f"bad_{out}")
            st, raw = create(name, out)
            guard(st, raw, tag)
            if st in (400, 422):
                print(f"[{tag}] out-of-range refused with {st} (clean)")
                if out == 0:
                    score, criteria, msg = check_error_quality(
                        raw, "max_resident_memory_percent")
                    print(f"[{tag}] rubric score={score}/3 criteria={criteria}; "
                          f"message={msg[:250]}")
                continue
            if 200 <= st <= 299:
                echoed = describe_mrmp(name)
                print(f"[{tag}] ACCEPTED with {st}; readback mrmp = {echoed!r}")
                if echoed == out:
                    defect("Type1_IllegalSuccess",
                           f"[{tag}] max_resident_memory_percent={out} (outside the "
                           f"closed interval [1, 100]) was accepted AND persisted as "
                           f"{echoed!r}; constraint qdrant_range_collections_create_006 "
                           f"is broken in both the acceptance and the state")
                print(f"[{tag}] accepted with the out-of-range value dropped "
                      f"(silent drop; acceptance recorded, state compliant)")
                continue
            script_error(f"[{tag}] unadjudicable status {st} (expected 400/422 or "
                         f"200-with-drop); raw={str(raw)[:200]}")

        # Type-2 rubric verdict folded into the 0-case handling above (report only)
        print("[summary] in-range 1/100 dual dispositions recorded; out-of-range "
              "0/101 neither persisted nor silently honored in state - the "
              "[1,100] bound holds per qdrant_range_collections_create_006")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
