#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_exists_004
# strategy: diagnosis_quality
# endpoint: collections+exists
# constraint_ids: qdrant_behavioral_collections_exists_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/collection-exists
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-02 (Error Message Negligence - the exists endpoint documents
#   ONLY a 200 response, so its error branches are the lowest-traffic code
#   paths in the whole collections API; exactly where generic bodies decay
#   unnoticed)
"""
Attack: diagnosis_quality (S2, Type-2) x qdrant_behavioral_collections_exists_001
  on collections+exists (chunk_collections+exists unit
  assertions::qdrant_behavioral_collections_exists_001).
  The assertion documents exactly one response: 200 with
  result.exists:boolean. When the face nevertheless emits an error for a
  malformed collection_name, this script does NOT adjudicate the status
  (accept/reject disposition for malformed names is the boundary lane's
  matrix - same scoping as R12 semantic_collections_delete_001, which graded
  404 bodies without re-adjudicating the 404); it grades the QUALITY of the
  error body with the Type-2 rubric:
    c1 resource named   - the body mentions "collection"/"collection_name" or
                          echoes the offending value (distinct prefix for the
                          overlong leg so echo-matching is unambiguous)
    c2 problem stated   - a format/range/not-found hint ("must be", "invalid",
                          "not found", "expected", "valid", "too long", ...)
    c3 actionable       - bonus only (suggests what to do)
  Legs:
    control             - self-created valid name -> 200 + result.exists True
                          (proves aliveness and attributes the error legs to
                          the malformed name, not to auth/transport wreckage)
    err-1 empty         - GET /collections//exists (empty path segment)
    err-2 overlong      - 300-char name (beyond any documented name budget;
                          spec-legal-but-extreme -> resource_bound style)
    err-3 illegal-chars - "bad name!" style value with spaces/punctuation
  A 200 answer on an error leg carries no error body -> nothing to grade
  (printed note; a 200 with result.exists=TRUE on a never-created malformed
  name is still a phantom-existence Type4). No by-design item in the threat
  model covers error-body quality, so this lane is fair game.
  [chunk_collections+exists coverage: diagnosis_quality x
   qdrant_behavioral_collections_exists_001 (error-body rubric on the
  malformed-name legs + valid control) - this script; core truthfulness+shape
   = _001; alias interplay = _002; cross-face equivalence = _003;
   legal-name family = _005]
Oracle: the control leg returns 200 with result.exists boolean True
  (otherwise SCRIPT_ERROR - premise); for every malformed leg that answers
  4xx, the body scores c1 AND c2 (names the resource/parameter and states
  the problem) - a 4xx body failing c1 or c2 = Type2_PoorDiagnostics
  (Blindspot BS-02); a malformed leg answered 200/false = conform-with-note
  (in-body existence answer, nothing to grade); a malformed leg answered
  200/true = Type4 phantom existence; 5xx with /healthz alive =
  Type3_RuntimeFailure; transport failure with healthy /healthz =
  SCRIPT_ERROR (G8).

Rationale (G5/G7/G9): the rubric breakdown is printed per leg so each
  criterion is auditable; expectation is declared before the measurement
  (score >= 2 of 3 with c1 and c2 mandatory); grading applies uniformly to
  every error body the face emits, so inconsistent quality across the
  malformed family is visible in the per-leg table.
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
# [path=collections+exists].url (the runtime PATHS table has no key for it)
EXISTS_KEY = "collection_exists"
EXISTS_URL = "/collections/{collection_name}/exists"
if EXISTS_KEY not in rt.PATHS:
    rt.PATHS[EXISTS_KEY] = EXISTS_URL
print(f"[path derivation] {EXISTS_KEY} = {rt.PATHS[EXISTS_KEY]} "
      f"(raw_knowledge api_endpoints[collections+exists].url)")

PFX = "sce04" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix
DIM = 4

PROBLEM_HINTS = ["must be", "expected", "should be", "valid", "range", "type",
                 "invalid", "not found", "doesn't exist", "does not exist",
                 "no collection", "unknown", "too long", "length", "format",
                 "characters", "empty", "missing", "non-empty"]
ACTION_HINTS = ["correct", "try", "use", "change", "specify", "provide",
                "check", "create", "list", "ensure"]


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


def error_text(raw):
    """Best diagnostic text from a raw body (qdrant nests it at
    status.error; fall back to the whole body; never assume a fixed shape)."""
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        b = None
    if isinstance(b, dict):
        se = b.get("status")
        if isinstance(se, dict) and isinstance(se.get("error"), str):
            return se["error"]
        if isinstance(b.get("error"), str):
            return b["error"]
        return json.dumps(b)
    return str(raw or "")


def grade_error_leg(label, value, echo_probe, st, raw, findings):
    """Type-2 rubric on one malformed-name leg. echo_probe is the substring
    expected if the body echoes the offending value."""
    text = error_text(raw)
    low = text.lower()
    c1 = ("collection" in low) or (echo_probe and echo_probe in low)
    c2 = any(h in low for h in PROBLEM_HINTS)
    c3 = any(h in low for h in ACTION_HINTS)
    score = int(c1) + int(c2) + int(c3)
    print(f"[{label}] status={st} rubric c1(resource-named)={c1} "
          f"c2(problem-stated)={c2} c3(actionable-bonus)={c3} score={score}/3 "
          f"text={text[:220]!r}")
    if st == 200:
        # answered in-body: nothing to grade (phantom check only)
        val = None
        try:
            res = json.loads(raw).get("result")
            if isinstance(res, dict):
                val = res.get("exists")
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
            val = None
        if val is True:
            findings.append((2, f"Type4_StateLogicViolation: {label} - malformed "
                                f"never-created name answered 200 with "
                                f"result.exists=true (phantom existence): "
                                f"{str(raw)[:200]!r}"))
        else:
            print(f"[note] {label}: answered 200 in-body (exists={val!r}) - "
                  f"no error body to grade (conform-with-note)")
        return
    if 400 <= st <= 499 and not (c1 and c2):
        findings.append((2, f"Type2_PoorDiagnostics: {label} - exists face "
                            f"returned {st} but the body fails the rubric "
                            f"(c1 resource-named={c1}, c2 problem-stated={c2}); "
                            f"the endpoint's error branches are undocumented "
                            f"(only 200 in expected_responses), so any error it "
                            f"does emit must at least name the resource and state "
                            f"the problem (Blindspot BS-02); body={str(raw)[:200]!r}"))
        return
    if 400 <= st <= 499:
        print(f"[conform] {label}: {st} with resource-named problem statement "
              f"(c3 actionable bonus={'yes' if c3 else 'no'})")


def main():
    print(f"ownership prefix: {PFX}")
    findings = []
    ctrl = PFX + "_ctrl"
    overlong = (PFX + "xmark") + "x" * 300      # ~311 chars, distinctive prefix
    illegal = "bad name! with spaces; punctuation"
    try:
        hs, hraw = safe_request("GET", "healthz", timeout=15)
        print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
        if hs != 200:
            print(f"VERDICT: SCRIPT_ERROR - /healthz pre-probe returned {hs}")
            sys.exit(2)

        # ---- control (G4): valid existing name -> 200 + result.exists True ----
        st, raw = safe_request("PUT", "create_collection",
                               body={"vectors": {"size": DIM, "distance": "Cosine"}},
                               path_params={"name": ctrl}, timeout=60)
        print(f"[create {ctrl}] status={st} raw={str(raw)[:200]}")
        if not transport_gate("create control", st, raw, findings):
            finish(findings)
            return
        if st not in (200, 201):
            findings.append((3, f"SCRIPT-ERROR-setup: create returned {st}: {str(raw)[:150]}"))
            finish(findings)
            return
        est, eraw = safe_request("GET", EXISTS_KEY,
                                 path_params={"collection_name": ctrl}, timeout=30)
        print(f"[control exists] status={est} raw={str(eraw)[:200]}")
        if not transport_gate("control exists", est, eraw, findings):
            finish(findings)
            return
        ok = False
        try:
            res = json.loads(eraw).get("result")
            ok = est == 200 and isinstance(res, dict) and res.get("exists") is True
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
            ok = False
        if not ok:
            findings.append((3, f"SCRIPT-ERROR-setup: control exists leg returned "
                                f"{est} (premise - cannot attribute error legs): "
                                f"{str(eraw)[:150]}"))
            finish(findings)
            return
        print("[conform] control: 200 with result.exists=true "
              "(error legs below are attributable to the malformed names)")

        # ---- error legs (disposition = boundary lane; body quality = here) ----
        legs = [
            ("err-1 empty name", "", ""),
            ("err-2 overlong name", overlong, PFX + "xmark"),
            ("err-3 illegal chars", illegal, "bad name!"),
        ]
        for label, value, echo in legs:
            st, raw = safe_request("GET", EXISTS_KEY,
                                   path_params={"collection_name": value}, timeout=30)
            print(f"[{label}] request issued for value_len={len(value)}")
            if transport_gate(label, st, raw, findings):
                grade_error_leg(label, value, echo, st, raw, findings)

        finish(findings)
    finally:
        # destructive-safety: only self-created, PFX-prefixed names are dropped
        try:
            rt.drop_collection(ctrl)
        except Exception as e:
            print(f"cleanup warning (drop {ctrl}): {e}")


def finish(findings):
    if findings:
        findings.sort(key=lambda x: x[0])
        rank, msg = findings[0]
        if rank == 3:
            print(f"VERDICT: SCRIPT_ERROR - {msg}")
            sys.exit(2)
        print(f"VERDICT: DEFECT_FOUND ({msg})")
        sys.exit(1)
    print("OK: every error body the exists face emitted for malformed names "
          "names the resource and states the problem (c1+c2 met); 200-answered "
          "legs carry no error body and no phantom existence")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)


if __name__ == "__main__":
    main()
