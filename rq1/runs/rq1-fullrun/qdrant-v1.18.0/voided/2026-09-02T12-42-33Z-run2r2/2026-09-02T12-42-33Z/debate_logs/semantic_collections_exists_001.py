#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_exists_001
# strategy: behavioral_contract
# endpoint: collections+exists
# constraint_ids: qdrant_behavioral_collections_exists_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/collection-exists
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - raw_knowledge's prose constraint says
#   "200 {result: bool}" while the spec-derived response_shape grid says
#   result=object with result.exists:boolean; D3b-2: spec-derived field wins,
#   so the oracle adjudicates result.exists, and a bare-bool result is a
#   measured shape conflict, not silently accepted)
"""
Attack: behavioral_contract (S1) x qdrant_behavioral_collections_exists_001
  on collections+exists (chunk_collections+exists unit
  assertions::qdrant_behavioral_collections_exists_001). This chunk OWNS the
  exists assertion; prior rounds (create/delete chunks) only used this face as
  a supporting probe, and boundary_collections_create_019 explicitly left a
  404-on-exists as "conform-with-note (conflict zone, not adjudicated)" -
  here the never-404 clause is adjudicated head-on. The assertion, quoted:
    "HTTP 200 with result being an object of shape {exists: bool}; a missing
     collection yields result.exists=false with HTTP 200 (never 404)"
  Legs (G4 positive/negative pairing on one setup):
    leg A positive   - self-created collection -> 200 with result an OBJECT
                       and result.exists exactly boolean True
    leg B negative   - never-created unique-prefix name -> 200 with
                       result.exists exactly boolean False; a 404 (or any
                       non-200) here violates the "never 404" clause
    leg B2 stability - the same never-created name probed again immediately;
                       the answer must not flap (same status+value)
    leg C transition - after a 200 delete of leg A's collection, exists must
                       flip to 200 + False
  Shape oracle (D3b-1, cross-checked against the endpoint response_shape
  grid BEFORE writing): result=object, result.exists=boolean are asserted;
  envelope status=string / time=number are printed as observed notes only
  (the assertion pins result.exists, not the envelope extras).
  BS-05 drift resolution (declared, per D3b-2): the raw_knowledge prose side
  says "200 {result: bool}" - if the live body returns a bare boolean result,
  that CONFLICTS with the spec-derived grid this script adjudicates against;
  it is recorded as a shape-conflict observation with the prose/grid source
  pair printed, not silently coerced.
  [chunk_collections+exists coverage: behavioral_contract x
   qdrant_behavioral_collections_exists_001 (truthfulness + never-404 +
   response-shape grid) - this script; alias interplay = _002; cross-face
   equivalence = _003; error-body quality = _004; legal-name family = _005]
Oracle: leg A returns 200 with result an object and result.exists boolean
  True; leg B/B2 return 200 with result.exists boolean False - a 404 or any
  non-200 on the never-created name = Type4_StateLogicViolation (existence
  wrongly expressed as an HTTP error, violating the assertion's never-404
  clause); result.exists=true on a never-created name or result.exists=false
  on the live one = Type4 (untruthful existence); a non-boolean exists value
  (string/number/null) or a non-object result = Type4 (response-shape grid
  result.exists:boolean violated); 5xx with /healthz alive = Type3;
  transport failure with healthy /healthz = SCRIPT_ERROR; create/delete
  setup failures = SCRIPT_ERROR (G8, never a defect).

Rationale (G4/G7/D3b): expectation declared per leg before measurement; the
  positive leg proves the face can report true (so B's false is existence
  semantics, not a broken face), and the negative leg proves a false answer
  is answered in-body rather than as an error - exactly the two halves of the
  assertion. Type checks use isinstance(v, bool) so "true"/1/None fail loudly.
"""

import os
import sys
import json
import time
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

# exists face: URL registered verbatim from raw_knowledge api_endpoints
# [path=collections+exists].url (the runtime PATHS table has no key for it -
# R13 dispatch lesson); template param is {collection_name}
EXISTS_KEY = "collection_exists"
EXISTS_URL = "/collections/{collection_name}/exists"
if EXISTS_KEY not in rt.PATHS:
    rt.PATHS[EXISTS_KEY] = EXISTS_URL
print(f"[path derivation] {EXISTS_KEY} = {rt.PATHS[EXISTS_KEY]} "
      f"(raw_knowledge api_endpoints[collections+exists].url)")

PFX = "sce01" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix
DIM = 4
ASSERT = ("HTTP 200 with result being an object of shape {exists: bool}; a missing "
          "collection yields result.exists=false with HTTP 200 (never 404)")


def safe_request(method, path_key, **kw):
    """Thin delegation to rt.request (DB-neutral path_key; forwards body/
    path_params/query_params/timeout exactly - standing lesson)."""
    return rt.request(method, path_key, **kw)


def healthz_ladder(label, attempts=3, delay=2):
    """G8 liveness re-check: inline safe_request('GET','healthz') probes."""
    for i in range(attempts):
        hs, hraw = safe_request("GET", "healthz", timeout=15)
        print(f"[healthz attempt {i + 1}] status={hs} raw={str(hraw)[:120]}")
        if 200 <= hs < 300:
            return None
        if i < attempts - 1:
            time.sleep(delay)
    return (f"Type3_RuntimeFailure(service-down) - '{label}': /healthz unreachable "
            f"after {attempts} attempts")


def transport_gate(label, st, raw, findings):
    """Three-outcome isolation (G8): True if adjudicable, False after recording."""
    if st <= 0:
        v = healthz_ladder(label)
        if v:
            findings.append((1, v))
        else:
            findings.append((3, f"SCRIPT-ERROR-transport: '{label}' failed with healthy /healthz: {str(raw)[:150]}"))
        return False
    if 500 <= st <= 599:
        v = healthz_ladder(label)
        findings.append((1, v if v else
                         f"Type3_RuntimeFailure: '{label}' got {st} with /healthz alive; body: {str(raw)[:200]}"))
        return False
    return True


def exists_face(name):
    """GET /collections/{collection_name}/exists -> (status, raw, result_obj,
    exists_value, shape_notes). shape_notes list the response-shape conflicts
    observed against the endpoint grid (result=object, result.exists=boolean)."""
    st, raw = safe_request("GET", EXISTS_KEY,
                           path_params={"collection_name": name}, timeout=30)
    notes = []
    res = None
    val = None
    try:
        env = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        env = None
    if not isinstance(env, dict):
        notes.append("envelope-not-object")
    else:
        # observed-only envelope notes (not part of the defect oracle)
        s, t = env.get("status"), env.get("time")
        print(f"[envelope note] status={s!r} ({type(s).__name__}) time={t!r} ({type(t).__name__})")
        res = env.get("result")
        if not isinstance(res, dict):
            notes.append(f"result-not-object({type(res).__name__})")
        else:
            v = res.get("exists")
            if not isinstance(v, bool):
                notes.append(f"exists-not-boolean({v!r} {type(v).__name__})")
            else:
                val = v
    return st, raw, res, val, notes


def judge_leg(label, name, st, raw, res, val, notes, expected, findings):
    """Declare-then-compare for one exists leg. expected is True/False."""
    print(f"[{label}] name={name!r} status={st} result={res!r} exists={val!r} "
          f"notes={notes} raw={str(raw)[:220]}")
    if st != 200:
        findings.append((2, f"Type4_StateLogicViolation: {label} - exists face "
                            f"returned HTTP {st} for collection_name={name!r}; the "
                            f"assertion qdrant_behavioral_collections_exists_001 "
                            f"requires 200 with existence expressed in the body "
                            f"('never 404'): {str(raw)[:200]!r}"))
        return
    if notes:
        findings.append((2, f"Type4_StateLogicViolation: {label} - response-shape "
                            f"grid violated (endpoint response_shape declares "
                            f"result=object, result.exists=boolean); observed "
                            f"conflicts: {notes}; BS-05 note: raw_knowledge prose "
                            f"side says '200 {{result: bool}}' - spec-derived grid "
                            f"wins per D3b-2: {str(raw)[:200]!r}"))
        return
    if val is not expected:
        findings.append((2, f"Type4_StateLogicViolation: {label} - result.exists="
                            f"{val!r} but ground truth is {expected!r} for "
                            f"collection_name={name!r}: {str(raw)[:200]!r}"))
        return
    print(f"[conform] {label}: 200 with result.exists={val!r} (object grid)")


def main():
    print(f"ownership prefix: {PFX}")
    print(f"[assertion quote] {ASSERT}")
    findings = []
    live = PFX + "_live"        # created by this script (positive leg)
    never = PFX + "_never"      # never created (negative leg; unique prefix)
    try:
        hs, hraw = safe_request("GET", "healthz", timeout=15)
        print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
        if hs != 200:
            print(f"VERDICT: SCRIPT_ERROR - /healthz pre-probe returned {hs}")
            sys.exit(2)

        # ---- setup: create the positive-leg collection ----
        st, raw = safe_request("PUT", "create_collection",
                               body={"vectors": {"size": DIM, "distance": "Cosine"}},
                               path_params={"name": live}, timeout=60)
        print(f"[create {live}] status={st} raw={str(raw)[:200]}")
        if not transport_gate("create live", st, raw, findings):
            finish(findings)
            return
        if st not in (200, 201):
            findings.append((3, f"SCRIPT-ERROR-setup: create returned {st}: {str(raw)[:150]}"))
            finish(findings)
            return

        # ---- leg A (positive): exists must be 200 + result.exists boolean True ----
        a = exists_face(live)
        judge_leg("leg A live collection", live, a[0], a[1], a[2], a[3], a[4], True, findings)

        # ---- leg B (negative): never-created name -> 200 + False, never 404 ----
        b = exists_face(never)
        judge_leg("leg B never-created", never, b[0], b[1], b[2], b[3], b[4], False, findings)

        # ---- leg B2 (stability): immediate re-probe must not flap ----
        b2 = exists_face(never)
        judge_leg("leg B2 re-probe stability", never, b2[0], b2[1], b2[2], b2[3], b2[4], False, findings)
        if b[0] == b2[0] and b[3] == b2[3]:
            print("[conform] re-probe stable (same status and value)")

        # ---- leg C (transition): after a 200 delete, exists flips to False ----
        st, raw = safe_request("DELETE", "drop_collection",
                               path_params={"name": live}, timeout=120)
        print(f"[delete {live}] status={st} raw={str(raw)[:200]}")
        if not transport_gate("delete live", st, raw, findings):
            finish(findings)
            return
        if st != 200:
            findings.append((3, f"SCRIPT-ERROR-setup: delete returned {st} "
                                f"(transition premise): {str(raw)[:150]}"))
            finish(findings)
            return
        c = exists_face(live)
        judge_leg("leg C post-delete", live, c[0], c[1], c[2], c[3], c[4], False, findings)

        finish(findings)
    finally:
        # destructive-safety: only self-created, PFX-prefixed names are dropped
        try:
            rt.drop_collection(live)
        except Exception as e:
            print(f"cleanup warning (drop {live}): {e}")


def finish(findings):
    if findings:
        findings.sort(key=lambda x: x[0])
        rank, msg = findings[0]
        if rank == 3:
            print(f"VERDICT: SCRIPT_ERROR - {msg}")
            sys.exit(2)
        print(f"VERDICT: DEFECT_FOUND ({msg})")
        sys.exit(1)
    print("OK: exists answers 200 in-body for live (true), never-created (false, "
          "stable) and just-deleted (false) names, with result an object and "
          "result.exists a real boolean (response-shape grid)")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)


if __name__ == "__main__":
    main()
