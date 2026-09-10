#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_optimizations_004
# strategy: diagnosis_quality
# endpoint: collections+optimizations
# constraint_ids: qdrant_behavioral_collections_optimizations_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-optimizations
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-02 (Error Message Negligence - the assertion's negative branch
#   is "404 for a missing collection"; a user hitting a typo'd collection name
#   needs the 404 body to say WHICH name failed and WHY. A bare/generic 404
#   that names neither the resource nor the problem is the diagnostic
#   negligence this blindspot covers)
"""
Attack: diagnosis_quality (S2, Type-2 rubric) x
  qdrant_behavioral_collections_optimizations_001 on collections+optimizations
  (chunk_collections+optimizations unit
  assertions::qdrant_behavioral_collections_optimizations_001; chunk coverage
  slot "diagnosis_quality (404 error body) x optimizations_001" - see _001's
  Attack block for the full chunk list).
  The negative branch of the assertion ("missing collection: HTTP 404") is
  exercised head-on; when the face answers 404 for a never-created VALID-
  format collection name, this script grades the QUALITY of the error body
  with the Type-2 rubric (content-graded only - the by-design note "error
  message field names like 'status'/'time'/'error' are not part of contract"
  is honored, no envelope-field assertions):
    c1 resource named - the body names the failing resource: the word
        "collection"/"collection_name" OR echoes the exact offending value
        (each never-created leg uses a distinct random suffix so an echo
        match is unambiguous);
    c2 problem stated - a not-found/format hint ("doesn't exist", "not
        found", "not exist", "missing", "invalid", "unknown");
    c3 actionable     - bonus only ("create", "check", "verify", "try",
        "ensure", "rename").
  A 404 body failing c1 OR c2 (empty body, bare status, no offending-name
  echo, no problem statement) = Type2_PoorDiagnostics.
Oracle: the control leg (self-created valid collection) answers HTTP 200
  with the published summary+running shape (premise aliveness - failure here
  = SCRIPT_ERROR, never a defect); every never-created valid-format name
  answers HTTP 404 (any non-404: 200 = Type4 phantom status report on a
  never-created name, 5xx with /healthz alive = Type3_RuntimeFailure) whose
  body MUST satisfy rubric c1 AND c2 (score >= 2/3) - missing either =
  Type2_PoorDiagnostics; c3 bonus only. The describe face's 404 body for the
  SAME missing name is fetched and graded as a cross-face comparison note
  only (the optimizations face is the adjudicated unit; a gross asymmetry
  where describe names the collection but optimizations does not is
  additional Type2 evidence, not a separate defect); transport failure with
  healthy /healthz = SCRIPT_ERROR (G8). Scoping: only VALID-format
  never-created names are graded - malformed-name disposition (empty/overlong
  segments) is the boundary lane's matrix, and router-level 404s for
  unmatchable paths are not a handler-diagnostics surface (same scoping as
  R12 semantic_collections_delete_001 / exists_004).
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

# ---- runtime PATHS gap: register the contract-derived URL (raw_knowledge only) ----
OPT_KEY = "collection_optimizations"
if OPT_KEY not in rt.PATHS:
    rt.PATHS[OPT_KEY] = "/collections/{collection_name}/optimizations"
print(f"[path derivation] {OPT_KEY} = {rt.PATHS[OPT_KEY]} (raw_knowledge "
      f"api_endpoints[collections+optimizations].url; runtime PATHS gap)")

PFX = "sco04" + uuid.uuid4().hex[:6]
DIM = 4
COL_OK = PFX + "_ok"
MISS_1 = PFX + "_missing_a_" + uuid.uuid4().hex[:8]
MISS_2 = PFX + "_missing_b_" + uuid.uuid4().hex[:8]

NOT_FOUND_HINTS = ("doesn't exist", "does not exist", "not found", "not exist",
                   "missing", "invalid", "unknown", "no such")
ACTION_HINTS = ("create", "check", "verify", "try", "ensure", "rename", "use",
                "provide", "change")


def safe_request(method, path_key, body=None, path_params=None, query_params=None,
                 timeout=30):
    """All HTTP through the runtime (DB-neutral path_key); forwards body/
    path_params/query_params/timeout exactly - standing lesson."""
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


def transport_guard(label, st, raw):
    """G8 three-outcome isolation."""
    if st <= 0 or 500 <= st <= 599:
        hs = liveness(label)
        if hs != 200:
            defect("Type3_RuntimeFailure",
                   f"service down - '{label}' got status={st} and /healthz={hs}")
        if st <= 0:
            script_error(f"transport failure '{label}' with healthy /healthz: {str(raw)[:150]}")
        defect("Type3_RuntimeFailure",
               f"'{label}' got {st} with /healthz alive; raw={str(raw)[:250]}")
    return st


def grade_404_body(raw, offending_name, label):
    """Type-2 rubric over the 404 body text (content only - envelope field
    names are by-design not part of contract). Returns (score, c1, c2).
    Failing c1 or c2 = Type2_PoorDiagnostics."""
    text = ""
    body = jload(raw)
    if isinstance(body, dict):
        # error text may live under status.error / error / status_description;
        # flatten ALL string values so grading is field-name agnostic
        parts = []

        def walk(node):
            if isinstance(node, dict):
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
            elif isinstance(node, str):
                parts.append(node)
        walk(body)
        text = " ".join(parts).lower()
        if not text and raw:
            text = raw.lower()
    elif raw:
        text = raw.lower()
    low = offending_name.lower()

    c1 = (low in text) or ("collection" in text)
    c2 = any(h in text for h in NOT_FOUND_HINTS)
    c3 = any(h in text for h in ACTION_HINTS)
    score = int(c1) + int(c2) + int(c3)
    print(f"[{label}] rubric c1(resource named)={c1} c2(problem stated)={c2} "
          f"c3(actionable, bonus)={c3} -> score {score}/3 "
          f"(text={text[:220]!r})")
    return score, c1, c2


def cleanup():
    """Teardown: drop only the collection created by this script;
    never-created names are never dropped."""
    try:
        rt.drop_collection(COL_OK)
    except Exception as e:
        print(f"cleanup warning (drop {COL_OK}): {e}")


def main():
    print(f"ownership prefix: {PFX}")
    print("[assertion quote] existing collection: HTTP 200 with per-shard "
          "optimizer status; missing collection: HTTP 404")
    try:
        # ---- control: premise aliveness on the optimizations face ----
        ok, err = rt.setup_default(COL_OK, dim=DIM, metric="Cosine")
        if not ok:
            script_error(f"premise create {COL_OK} failed: {err}")
        st, raw = safe_request("GET", OPT_KEY, path_params={"collection_name": COL_OK},
                               timeout=30)
        print(f"[control GET optimizations {COL_OK}] status={st} raw={str(raw)[:400]}")
        transport_guard("control", st, raw)
        if st != 200:
            script_error(f"control leg on existing {COL_OK} answered {st}: {str(raw)[:200]}")
        body = jload(raw)
        res = body.get("result") if isinstance(body, dict) else None
        if not isinstance(res, dict) or not isinstance(res.get("summary"), dict):
            script_error(f"control leg 200 body lacks the promised summary result: {str(raw)[:200]}")

        # ---- err-1 / err-2: never-created valid-format names -> 404 with quality ----
        for miss in (MISS_1, MISS_2):
            st, raw = safe_request("GET", OPT_KEY, path_params={"collection_name": miss},
                                   timeout=30)
            print(f"[404 leg {miss}] status={st} raw={str(raw)[:300]}")
            transport_guard(f"404 leg {miss}", st, raw)
            if st == 200:
                defect("Type4_StateLogicViolation",
                       f"never-created valid-format name {miss} answered HTTP 200 with "
                       f"an optimizer status report; the assertion negative branch "
                       f"promises 404 (phantom): {str(raw)[:300]!r}")
            if st != 404:
                defect("Type4_StateLogicViolation",
                       f"never-created valid-format name {miss} answered HTTP {st}; "
                       f"assertion negative branch promises exactly 404: {str(raw)[:300]!r}")
            score, c1, c2 = grade_404_body(raw, miss, f"404-leg {miss}")
            if not (c1 and c2):
                defect("Type2_PoorDiagnostics",
                       f"404 for missing collection {miss} failed the Type-2 rubric: "
                       f"c1(resource named)={c1}, c2(problem stated)={c2}; the body "
                       f"does not say which collection is wrong or why - a user hitting "
                       f"a typo'd name cannot diagnose it (BS-02): {str(raw)[:300]!r}")

        # ---- cross-face note: describe's 404 body for the SAME missing name ----
        st, raw_d = safe_request("GET", "describe_collection", path_params={"name": MISS_1},
                                 timeout=30)
        print(f"[cross-face describe {MISS_1}] status={st} raw={str(raw_d)[:300]}")
        transport_guard("cross-face describe", st, raw_d)
        if st == 404:
            score_d, c1_d, c2_d = grade_404_body(raw_d, MISS_1, "describe-face")
            print(f"[cross-face note] describe 404 for the same name scored "
                  f"{score_d}/3 with c1={c1_d} c2={c2_d} (optimizations face scored "
                  f"above; comparison recorded, only the optimizations face is "
                  f"adjudicated - gross asymmetry would be additional Type2 evidence)")
        else:
            print(f"[cross-face note] describe answered {st} for {MISS_1} "
                  f"(recorded, not adjudicated here)")

        print(f"OK: never-created names {MISS_1}/{MISS_2} each answered 404 with a "
              f"body naming the failing resource (c1) and stating the problem (c2); "
              f"control {COL_OK} answered 200 with the promised summary shape")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
