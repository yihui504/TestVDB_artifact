#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_create_008
# strategy: behavioral_contract
# endpoint: collections+create
# constraint_ids: qdrant_range_collections_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-02 (Error Message Negligence - a refused timeout value must
#   still name the parameter and hint the minimum) + BS-04 (boundary: min 1)
"""
Attack: behavioral_contract + diagnosis_quality x
  qdrant_range_collections_create_001 (chunk_collections+create-1of2;
  PUT /collections/{name}?timeout=N, path_key create_collection from runtime
  PATHS, URL from raw_knowledge api_endpoints[collections+create].url). The
  assertion (evidence_tier=explicit): the timeout QUERY parameter has schema
  minimum 1 (seconds). Standing lesson: wait/timeout-class params go in the
  URL query string (query_params forwarded to rt.request), never the body.
  Probes (fresh name each):
    - ?timeout=1 -> boundary closure: must be accepted 200 result=true (the
      minimum itself is legal - G4 boundary closure)
    - ?timeout=0 -> below minimum: must be refused 400/422; the rejection
      message is scored on the Type-2 rubric (names 'timeout' / hints the
      minimum-range / gives an actionable suggestion)
    - ?timeout=-3 -> negative: must be refused
    - ?timeout=1.5 -> non-integer: must be refused
  [chunk_collections+create-1of2 coverage: behavioral_contract x
   qdrant_range_collections_create_001 (min-1 closure) + diagnosis_quality x
   qdrant_range_collections_create_001 (timeout=0 message rubric)]
Oracle: ?timeout=1 creates 200 result=true (refusal = Type1_IllegalRejection);
  ?timeout=0, ?timeout=-3 and ?timeout=1.5 are each refused 400/422 (any 2xx
  = Type1_IllegalSuccess; 5xx with /healthz alive = Type3_RuntimeFailure);
  the timeout=0 rejection message scores >= 1/3 on the rubric
  (param_named + format_hint + actionable; 0/3 = Type2_PoorDiagnostics) -
  constraint qdrant_range_collections_create_001 (timeout minimum 1).

Rationale (G4/G5/G7): the closed minimum and its just-below neighbor are
probed on the same legal body so the disposition pair isolates the boundary;
the refusal text is judged against the BS-02 rubric so a silent or nameless
rejection cannot pass as diagnostics.
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

PREFIX = "scc08_"
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


def create_q(name, timeout_value):
    """Create with the timeout as a URL query parameter (never in the body)."""
    st, raw = safe_request("PUT", "create_collection", {"vectors": DENSE},
                           path_params={"name": name},
                           query_params={"timeout": timeout_value})
    print(f"[create {name} ?timeout={timeout_value!r}] status={st} raw={str(raw)[:300]}")
    if st in (200, 201):
        CREATED.append(name)
    return st, raw


def check_error_quality(status, raw, expected_param):
    """Type-2 diagnosis quality rubric (parameter_named 1pt + format_hint 1pt
    + actionable 1pt). body may be dict or str."""
    body = jload(raw) if isinstance(raw, str) else raw
    error_msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()
    score = 0
    detail = []
    if expected_param.lower() in error_msg:
        score += 1
        detail.append("param_named")
    format_hints = ["must be", "expected", "should be", "valid", "range",
                    "type", "positive", "non-zero", "at least", "minimum",
                    "greater", "integer"]
    hit = [h for h in format_hints if h in error_msg]
    if hit:
        score += 1
        detail.append(f"format_hint({hit[0]})")
    action_hints = ["correct", "try", "use", "change", "specify", "provide"]
    hit2 = [h for h in action_hints if h in error_msg]
    if hit2:
        score += 1
        detail.append(f"actionable({hit2[0]})")
    return score, detail, error_msg


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

        # ---- boundary closure: timeout=1 must be accepted ----
        st, raw = create_q(mkn("ok_t1"), 1)
        guard(st, raw, "timeout=1 closure")
        if st != 200:
            defect("Type1_IllegalRejection",
                   f"[timeout=1 closure] the schema minimum itself must be accepted "
                   f"(constraint qdrant_range_collections_create_001: timeout minimum "
                   f"1); got {st}; raw={str(raw)[:250]}")
        b = jload(raw)
        if not isinstance(b, dict) or b.get("result") is not True:
            defect("Type4_StateLogicViolation",
                   f"[timeout=1 closure] 200 body must carry result=true "
                   f"(response_shape result:boolean); raw={str(raw)[:250]}")
        print("[timeout=1 closure] accepted with 200 and result=true")

        # ---- violations: 0, -3, 1.5 must be refused ----
        for tag, val, why in [
            ("t0", 0, "timeout=0 is below the schema minimum 1"),
            ("tneg", -3, "timeout=-3 is negative"),
            ("tfloat", 1.5, "timeout=1.5 is not an integer"),
        ]:
            st, raw = create_q(mkn(f"bad_{tag}"), val)
            guard(st, raw, tag)
            if 200 <= st <= 299:
                defect("Type1_IllegalSuccess",
                       f"[{tag}] ?timeout={val!r} ({why}) was ACCEPTED with status {st}; "
                       f"constraint qdrant_range_collections_create_001 declares "
                       f"timeout minimum 1 (seconds); raw={str(raw)[:250]}")
            if st not in (400, 422):
                script_error(f"[{tag}] unadjudicable refusal status {st} "
                             f"(expected 400/422); raw={str(raw)[:200]}")
            print(f"[{tag}] cleanly rejected with {st}")

        # ---- Type-2 rubric on the timeout=0 rejection ----
        st, raw = create_q(mkn("rubric_t0"), 0)
        guard(st, raw, "rubric timeout=0")
        if st in (400, 422):
            score, detail, msg = check_error_quality(st, raw, "timeout")
            print(f"[rubric timeout=0] score={score}/3 criteria={detail} "
                  f"message={msg[:250]}")
            if score == 0:
                defect("Type2_PoorDiagnostics",
                       f"[rubric timeout=0] the refusal for ?timeout=0 (below the "
                       f"documented minimum 1) names no parameter, gives no "
                       f"format/range hint and no actionable suggestion (0/3 on the "
                       f"Type-2 rubric); raw={str(raw)[:250]}")
            print(f"[rubric timeout=0] diagnostics carry >=1 rubric criterion "
                  f"({detail}) - acceptable")
        elif 200 <= st <= 299:
            defect("Type1_IllegalSuccess",
                   f"[rubric timeout=0] ?timeout=0 ACCEPTED with {st} (schema minimum "
                   f"is 1); raw={str(raw)[:250]}")
        else:
            script_error(f"[rubric timeout=0] unadjudicable status {st}; "
                         f"raw={str(raw)[:200]}")

        print("[summary] timeout=1 closure accepted; timeout=0/-3/1.5 refused; "
              "timeout=0 refusal carries rubric diagnostics - constraint "
              "qdrant_range_collections_create_001 holds")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
