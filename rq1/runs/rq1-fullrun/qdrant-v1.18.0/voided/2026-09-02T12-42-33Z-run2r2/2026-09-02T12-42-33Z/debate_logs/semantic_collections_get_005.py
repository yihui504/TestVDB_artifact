#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_get_005
# strategy: diagnosis_quality
# endpoint: collections+get
# constraint_ids: qdrant_behavioral_collections_get_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-02 (Error Message Negligence - the team prioritizes
#   functional correctness over diagnostic quality; this chunk's assertion
#   documents the 404 body verbatim ('Not found: Collection ... doesn't
#   exist!'), so a live body that is empty, generic ('internal error'), or
#   nameless is a measurable regression against the documented diagnostic)
"""
Attack: diagnosis_quality (S2, Type-2) x qdrant_behavioral_collections_get_001
  on collections+get (chunk_collections+get unit
  assertions::qdrant_behavioral_collections_get_001). The assertion's miss
  branch, quoted: "missing collection: HTTP 404 with an error message
  (runtime verified: 'Not found: Collection ... doesn't exist!'), never
  200 with config". _001 adjudicates the STATUS half of that branch; this
  script grades the QUALITY of the error body with the Type-2 rubric
  (parameter_named + format/problem hint + actionable bonus; the
  disposition of malformed names is the boundary lane's matrix - same
  scoping as R13 semantic_collections_exists_004, which graded error
  bodies without re-adjudicating statuses):
    c1 resource/param named - the body mentions "collection" (the endpoint's
       only request parameter resource) OR echoes the offending name (each
       leg carries a distinct uuid-marked segment so echo-matching is
       unambiguous even if the server truncates)
    c2 problem stated     - a not-found/format hint: "not found", "doesn't
       exist", "must be", "expected", "should be", "valid", "range",
       "type", "invalid", "too long", "exceed", "limit", "non-zero",
       "positive"
    c3 actionable (bonus) - "correct", "try", "use", "change", "specify",
       "provide"
  Legs (all never-created; distinct prefixes; no name is created or
  deleted by this script):
    n1 ordinary      - ordinary-format never-created name; 404 is the
                       documented answer, and its body is graded
    n2 overlong      - 300-char name (legal-grammar family pushed past any
                       plausible length limit); whatever 4xx arrives, only
                       its BODY quality is graded here
    n3 spaced        - name containing a space (sent URL-encoded); whatever
                       4xx arrives, only its BODY quality is graded here
  Scoring: a leg fails when c1+c2 (the two mandatory criteria) are not
  both met (score < 2) -> Type2_PoorDiagnostics. c3 alone missing is
  conform-with-note (bonus per the rubric).
  [chunk_collections+get coverage: diagnosis_quality x
   qdrant_behavioral_collections_get_001 (miss-branch error-body quality
   rubric) - this script; 200-full-config grid vs 404 = _001; config-echo
   = _002; counter truthfulness = _003; metamorphic alias equivalence =
   _004; legal-name family = _006]
Oracle: for every graded leg (4xx returned) the error body earns at least
  the two mandatory rubric points - it names the resource ("collection")
  or echoes the submitted name, AND states the problem (not-found/format
  hint); any leg scoring < 2 = Type2_PoorDiagnostics (BS-02: the
  documented diagnostic 'Not found: Collection `X` doesn't exist!' earns
  exactly c1+c2, so this is the measurable floor); a 404 with an
  empty/missing error body = Type2 as well (nothing to diagnose from); a
  200 on a never-created name is NOT adjudicated here (that is _001's
  Type1_IllegalSuccess lane) - the leg is skipped with a printed note;
  5xx with /healthz alive = Type3; transport failure with healthy
  /healthz = SCRIPT_ERROR (G8); no setup exists that can fail (no
  collection is created or deleted by this script).

Rationale (G3/G7/BS-02): the rubric's mandatory pair mirrors the
  assertion's own runtime-verified message, which names the resource and
  the problem but offers no action - conform-with-note at 2/3 is the
  honest expected floor, so a defect verdict can only come from a real
  diagnostic regression (empty/generic/nameless body), never from
  demanding more than the documented contract shows.
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

# describe face: runtime PATHS key describe_collection, cross-checked against
# raw_knowledge api_endpoints[path=collections+get].url = /collections/{collection_name}
DESCRIBE_KEY = "describe_collection"
print(f"[path derivation] {DESCRIBE_KEY} = {rt.PATHS[DESCRIBE_KEY]} "
      f"(runtime PATHS; matches raw_knowledge api_endpoints[collections+get].url "
      f"/collections/{{collection_name}})")

PFX = "scg05" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix

PROBLEM_HINTS = ("not found", "doesn't exist", "does not exist", "must be",
                 "expected", "should be", "valid", "range", "type", "invalid",
                 "too long", "exceed", "limit", "non-zero", "positive")
ACTION_HINTS = ("correct", "try", "use ", "change", "specify", "provide")


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


def extract_error(env):
    """Pull the error text out of a qdrant error envelope
    ({'status': {'error': ...}} per the runtime-verified 404 body)."""
    if not isinstance(env, dict):
        return None
    st = env.get("status")
    if isinstance(st, dict) and isinstance(st.get("error"), str) and st.get("error"):
        return st["error"]
    for k in ("err", "error", "message", "detail"):
        v = env.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def grade_error_body(label, name, echo_marker, status, raw, env, findings):
    """Type-2 rubric on one leg's error body. echo_marker is the leg-unique
    uuid-marked substring that an honest echo of the submitted name contains."""
    text = extract_error(env)
    if not text:
        # fall back to the whole raw body so an error carried outside the
        # documented envelope is still graded rather than ignored
        text = raw if isinstance(raw, str) and raw.strip() else None
    print(f"[{label}] name_len={len(name)} status={status} error_text={str(text)[:260]!r}")
    if not text:
        findings.append((2, f"Type2_PoorDiagnostics: {label} - HTTP {status} arrived "
                            f"with an empty/unparseable error body; the assertion "
                            f"requires '404 with an error message' and BS-02's floor "
                            f"is a body one can diagnose from: raw={str(raw)[:200]!r}"))
        return
    low = text.lower()
    c1 = ("collection" in low) or (echo_marker in text)
    c2 = any(h in low for h in PROBLEM_HINTS)
    c3 = any(h in low for h in ACTION_HINTS)
    score = (1 if c1 else 0) + (1 if c2 else 0) + (1 if c3 else 0)
    print(f"[{label}] rubric: c1 resource/echo-named={c1} c2 problem-stated={c2} "
          f"c3 actionable={c3} (bonus) -> score {score}/3")
    if not (c1 and c2):
        findings.append((2, f"Type2_PoorDiagnostics: {label} - error body scores "
                            f"{score}/3 (c1 resource/echo-named={c1}, c2 problem-"
                            f"stated={c2}, c3 actionable bonus={c3}); the two "
                            f"mandatory criteria are not both met. Body: "
                            f"{str(text)[:200]!r}"))
    elif not c3:
        print(f"[note] {label}: conform at 2/3 - no actionable suggestion (bonus "
              f"criterion; the assertion's own documented message also lacks one)")


def main():
    print(f"ownership prefix: {PFX}")
    findings = []
    # never-created legs, each with a distinct marker segment for echo-matching;
    # this script creates and deletes NOTHING
    legs = [
        ("n1 ordinary unknown", PFX + "_n1_" + "ordinary", PFX + "_n1_"),
        ("n2 overlong 300-char", PFX + "_n2_" + "z" * 300, PFX + "_n2_"),
        ("n3 spaced name", PFX + "_n3_" + "bad name", PFX + "_n3_"),
    ]
    try:
        hs, hraw = safe_request("GET", "healthz", timeout=15)
        print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
        if hs != 200:
            print(f"VERDICT: SCRIPT_ERROR - /healthz pre-probe returned {hs}")
            sys.exit(2)

        for label, name, marker in legs:
            st, raw = safe_request("GET", DESCRIBE_KEY,
                                   path_params={"name": name}, timeout=30)
            print(f"[{label}] status={st} raw={str(raw)[:260]}")
            if not transport_gate(f"describe {label}", st, raw, findings):
                finish(findings)
                return
            if 200 <= st < 300:
                print(f"[note] {label}: got {st} on a never-created name - the "
                      f"never-200 clause is _001's Type1 lane; quality leg skipped "
                      f"here to avoid double adjudication (G3)")
                continue
            if 400 <= st < 500:
                try:
                    env = json.loads(raw) if raw else None
                except (json.JSONDecodeError, ValueError, TypeError):
                    env = None
                grade_error_body(label, name, marker, st, raw, env, findings)
            else:
                print(f"[note] {label}: unexpected status class {st} - not graded "
                      f"(neither documented 404 nor a 4xx quality leg)")

        finish(findings)
    finally:
        # no cleanup needed: this script never creates collections or aliases
        pass


def finish(findings):
    if findings:
        findings.sort(key=lambda x: x[0])
        rank, msg = findings[0]
        if rank == 3:
            print(f"VERDICT: SCRIPT_ERROR - {msg}")
            sys.exit(2)
        print(f"VERDICT: DEFECT_FOUND ({msg})")
        sys.exit(1)
    print("OK: every graded miss/error body names the resource (or echoes the "
          "submitted name) and states the problem - the two mandatory Type-2 "
          "criteria; actionable suggestions remain bonus-only")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)


if __name__ == "__main__":
    main()
