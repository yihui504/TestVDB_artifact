#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_delete_001
# strategy: diagnosis_quality
# endpoint: collections+delete
# constraint_ids: qdrant_behavioral_collections_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-02 (Error Message Negligence - the team treats generic error
#   bodies as acceptable for edge cases; the 404 path of DELETE is exactly the
#   low-traffic branch where diagnostic quality decays unnoticed)
"""
Attack: diagnosis_quality (Type2) x qdrant_behavioral_collections_delete_001
  on collections+delete (chunk_collections+delete unit
  assertions::qdrant_behavioral_collections_delete_001).
  The assertion pins the negative disposition: DELETE of a non-existent
  collection returns 404 "not found" (raw_knowledge expected_responses
  {"404": "not found"}). This script does NOT re-adjudicate the status (the
  boundary lane owns the disposition matrix); it grades the QUALITY of that
  404 body with the Type-2 rubric:
    c1 resource named  - the requested collection name (or at least the word
                         "collection") appears in the error text
    c2 not-found hint  - text states not-found semantics ("not found",
                         "doesn't exist", "no collection", ...)
    c3 actionable      - bonus only (a suggestion like "create it first")
  G4 pairing: a control leg deletes a really-existing (self-created)
  collection and must get 200 + envelope result=true - proving the 404s below
  come from non-existence, not from auth/transport wreckage.
  G9 face-consistency: the GET /collections/{name} 404 body is scored with the
  same rubric and used as the reference face; if the read face names the
  resource but the DELETE face does not, diagnostics are inconsistent across
  faces of the same parameter (collection_name) - counted as the same Type2
  defect family.
  Threat-model note: the by-design item "Idempotent DELETE returns 200 even if
  point doesn't exist" is POINTS-level; this collection-level assertion
  explicitly requires 404 - the two are not conflated here.
  [chunk_collections+delete coverage: diagnosis_quality x
   qdrant_behavioral_collections_delete_001 (404 body rubric + GET-face
   reference) - this script; the 200/404 status matrix itself is the boundary
   lane's, not duplicated]
Oracle: DELETE of a never-created name (unique run prefix) returns 404 whose
  body scores c1 AND c2 of the rubric (names the collection, states
  not-found); a 404 with a generic/bodyless reply failing c1 or c2 =
  Type2_PoorDiagnostics; the control delete returns 200 with envelope
  result=true (otherwise SCRIPT_ERROR - setup premise); 5xx with /healthz
  alive = Type3_RuntimeFailure.

Rationale (G5/G7/G9): expectation declared before measurement - the rubric
  breakdown is printed for every leg so the judge can audit each criterion;
  the read-face 404 is adjudicated with the identical rubric so any asymmetry
  is a named, spec-anchored observation rather than an eyeball call.
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

print("[path derivation] drop_collection = /collections/{name} "
      "(raw_knowledge api_endpoints[collections+delete].url = /collections/{collection_name})")

PFX = "scd01" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix
DIM = 4
CREATED = []


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
    """Extract the best diagnostic text from a raw body (qdrant nests it at
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


NOTFOUND_HINTS = ["not found", "doesn't exist", "does not exist", "doesn`t exist",
                  "no collection", "unknown collection", "nonexistent", "non-existent",
                  "missing", "not exist"]
ACTION_HINTS = ["create", "check", "verify", "use", "specify", "provide", "list", "try"]


def grade_404(label, st, raw, name, findings):
    """Type-2 rubric on one 404 leg. Returns True if the leg is conformant
    (status 404 AND c1 AND c2), False after recording a finding otherwise."""
    text = error_text(raw)
    low = text.lower()
    c1 = (name in text) or ("collection" in low)
    c2 = any(h in low for h in NOTFOUND_HINTS)
    c3 = any(h in low for h in ACTION_HINTS)
    score = int(c1) + int(c2) + int(c3)
    print(f"[{label}] status={st} rubric c1(name-or-collection)={c1} "
          f"c2(not-found-hint)={c2} c3(actionable-bonus)={c3} score={score}/3 "
          f"text={text[:220]!r}")
    if st != 404:
        findings.append((3, f"SCRIPT-ERROR: {label} expected the declared 404 "
                            f"(raw_knowledge expected_responses), got {st}; "
                            f"status-matrix adjudication belongs to the boundary lane: "
                            f"{str(raw)[:150]}"))
        return False
    if not (c1 and c2):
        findings.append((2, f"Type2_PoorDiagnostics: {label} returned 404 but the body "
                            f"fails the rubric (c1 resource-named={c1}, c2 not-found-hint={c2}); "
                            f"constraint qdrant_behavioral_collections_delete_001 requires "
                            f"404 'not found' with a usable diagnostic (Blindspot BS-02); "
                            f"body={str(raw)[:200]!r}"))
        return False
    print(f"[conform] {label}: 404 with resource-named not-found diagnostic "
          f"(c3 actionable bonus={'yes' if c3 else 'no'})")
    return True


def main():
    print(f"ownership prefix: {PFX}")
    findings = []
    ctrl = PFX + "_ctrl"       # really created, then deleted (control leg)
    never = PFX + "_never"     # never created by this script (or any: unique PFX)
    CREATED.append(ctrl)
    try:
        hs, hraw = safe_request("GET", "healthz", timeout=15)
        print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
        if hs != 200:
            print(f"VERDICT: SCRIPT_ERROR - /healthz pre-probe returned {hs}")
            sys.exit(2)

        # ---- G4 control: delete of a really-existing collection ----
        st, raw = safe_request("PUT", "create_collection",
                               body={"vectors": {"size": DIM, "distance": "Cosine"}},
                               path_params={"name": ctrl}, timeout=60)
        print(f"[create {ctrl}] status={st} raw={str(raw)[:200]}")
        if st != 200:
            print(f"VERDICT: SCRIPT_ERROR - control create failed with {st} (setup premise, no defect claim)")
            sys.exit(2)
        st, raw = safe_request("DELETE", "drop_collection",
                               path_params={"name": ctrl}, timeout=60)
        print(f"[control delete {ctrl}] status={st} raw={str(raw)[:200]}")
        if not transport_gate("control delete", st, raw, findings):
            finish(findings)
            return
        try:
            env = json.loads(raw) if raw else {}
            ok_env = isinstance(env.get("result"), bool) and env["result"]
        except Exception:
            ok_env = False
        if st != 200:
            # disposition matrix is the boundary lane's; here it breaks the premise
            findings.append((3, f"SCRIPT-ERROR: control delete of an existing collection "
                                f"got {st}; cannot attribute the 404 legs to non-existence: "
                                f"{str(raw)[:150]}"))
        elif not ok_env:
            findings.append((2, "Type4_StateLogicViolation: control delete 200 but envelope "
                                "violates result:boolean=true grid "
                                "(collections+delete response_shape)"))
        else:
            print("[conform] control delete: 200 with result=true "
                  "(404s below are attributable to non-existence)")

        # ---- attack leg 1: DELETE of a never-created name ----
        st, raw = safe_request("DELETE", "drop_collection",
                               path_params={"name": never}, timeout=60)
        print(f"[delete never-created {never}] status={st} raw={str(raw)[:300]}")
        if transport_gate("delete never-created", st, raw, findings):
            grade_404("delete never-created", st, raw, never, findings)

        # ---- attack leg 2: DELETE of the just-deleted control name ----
        st, raw = safe_request("DELETE", "drop_collection",
                               path_params={"name": ctrl}, timeout=60)
        print(f"[delete just-deleted {ctrl}] status={st} raw={str(raw)[:300]}")
        if transport_gate("delete just-deleted", st, raw, findings):
            grade_404("delete just-deleted", st, raw, ctrl, findings)

        # ---- G9 reference face: GET of the same never-created name ----
        gst, graw = safe_request("GET", "describe_collection",
                                 path_params={"name": never}, timeout=30)
        print(f"[get never-created {never}] status={gst} raw={str(graw)[:300]}")
        if transport_gate("get never-created", gst, graw, findings):
            grade_404("get never-created (reference face)", gst, graw, never, findings)

        finish(findings)
    finally:
        # destructive-safety: only self-created, PFX-prefixed names are dropped
        for n in list(CREATED):
            try:
                rt.drop_collection(n)
            except Exception as e:
                print(f"cleanup warning (drop {n}): {e}")


def finish(findings):
    if findings:
        findings.sort(key=lambda x: x[0])
        rank, msg = findings[0]
        if rank == 3:
            print(f"VERDICT: SCRIPT_ERROR - {msg}")
            sys.exit(2)
        print(f"VERDICT: DEFECT_FOUND ({msg})")
        sys.exit(1)
    print("OK: DELETE 404 bodies name the missing collection and state not-found "
          "semantics on both the delete face and the GET reference face "
          "(c1+c2 met; control delete 200 result=true)")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)


if __name__ == "__main__":
    main()
