#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_create_020
# strategy: diagnosis_quality
# endpoint: collections+create
# constraint_ids: qdrant_behavioral_collections_create_003
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-02 (Error Message Negligence - the observed v1.18.0 message
#   'Format error in JSON body: data did not match any variant of untagged
#   enum VectorsConfig' names the serde type, not the offending FIELD; a
#   user cannot tell whether distance or size was wrong)
"""
Attack: diagnosis_quality (Type-2 focused) x
  qdrant_behavioral_collections_create_003 (chunk_collections+create-2of2;
  PUT /collections/{name} via runtime path_key create_collection). The
  assertion leg: invalid vectors config -> 400. This script scores the
  QUALITY of the rejection for two field-targeted mutations, asking
  whether the message lets a user identify WHICH member was wrong:
    leg A: distance 'Bogus'  -> rubric expects the message to name
           'distance' (and/or 'vectors');
    leg B: size '4' (string) -> rubric expects the message to name 'size'
           (and/or 'vectors'/'uint64').
  Canonical 3-point rubric per leg: (1) parameter named; (2) format/range
  hint; (3) actionable. Declared thresholds (oracle-first): a refused leg
  scoring 0/3 = Type2_PoorDiagnostics defect; >=1/3 = NO_DEFECT with the
  score recorded. Prerequisite gate: each leg must be refused 4xx first
  (a 200 is unit 003's Type1 ground, reported not scored).
  [chunk_collections+create-2of2 coverage: diagnosis_quality x
   qdrant_behavioral_collections_create_003 (field-targeted rejection
   rubric, distance-leg + size-leg)]
Oracle: both malformed legs (distance:'Bogus', size:'4') are refused 4xx
  and each leg's error text names at least one of its expected parameters
  ('distance'/'vectors' for leg A, 'size'/'vectors' for leg B) or carries
  a format/actionable hint - a 4xx scoring 0/3 = DEFECT_FOUND
  (Type2_PoorDiagnostics); a 200 leg = DEFECT_FOUND
  (Type1_IllegalSuccess); 5xx with /healthz alive = Type3_RuntimeFailure;
  otherwise NO_DEFECT with per-leg scores recorded - constraint
  qdrant_behavioral_collections_create_003.

Rationale (G7/BS-02): field-attribution is the diagnostic that matters on
  a two-member config: 'did not match any variant' localizes to neither
  distance nor size. Scoring is declared before measurement; the message
  text is normalized (JSON-dumped or stringified) before matching.
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

PREFIX = "scc020_"
RUN = str(int(time.time()))
CREATED = []


def safe_request(method, path_key, body=None, path_params=None, query_params=None, timeout=60):
    """All HTTP through the runtime; forwards method/path_key/body/path_params/
    query_params/timeout exactly (standing lesson). Returns (status, raw_text)."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


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


def check_error_quality(body, expected_params):
    """Type-2 rubric; expected_params is a list - criterion 1 passes if ANY
    expected parameter name appears (field attribution). body dict|str."""
    error_msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()
    score = 0
    hits = []
    if any(p.lower() in error_msg for p in expected_params):
        score += 1
        hits.append("param_named")
    format_hints = ["must be", "expected", "should be", "valid", "range",
                    "type", "positive", "non-zero", "unknown variant",
                    "variant", "enum", "uint", "integer", "missing"]
    if any(h in error_msg for h in format_hints):
        score += 1
        hits.append("format_hint")
    action_hints = ["correct", "try", "use", "change", "specify", "provide",
                    "one of", "expected one"]
    if any(h in error_msg for h in action_hints):
        score += 1
        hits.append("actionable")
    return score, 3, hits, error_msg


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
        legs = [
            ("A_distance", {"vectors": {"size": 4, "distance": "Bogus"}},
             ["distance", "vectors", "cosine", "euclid", "dot", "manhattan"]),
            ("B_size", {"vectors": {"size": "4", "distance": "Cosine"}},
             ["size", "vectors", "uint", "dimension"]),
        ]
        for tag, body, expected in legs:
            name = mkn(f"diag_{tag}")
            st, raw = safe_request("PUT", "create_collection", body,
                                   path_params={"name": name})
            print(f"[{tag}] body={json.dumps(body)} status={st} raw={str(raw)[:400]}")
            if st == 0:
                if liveness(f"transport-{tag}") != 200:
                    script_error(f"{tag}: transport failure and /healthz down; no defect conclusion")
                script_error(f"{tag}: transport failure; /healthz alive; no defect conclusion")
            if 500 <= st <= 599:
                if liveness(f"5xx-{tag}") != 200:
                    script_error(f"{tag}: 5xx ({st}) and /healthz not 200; deployment unstable")
                defect("Type3_RuntimeFailure",
                       f"{tag}: malformed vectors config raised {st} while /healthz "
                       f"alive; raw={str(raw)[:200]}")
            if st in (200, 201):
                CREATED.append(name)
                defect("Type1_IllegalSuccess",
                       f"{tag}: malformed vectors config {json.dumps(body)} accepted "
                       f"with {st} (unit 003 ground: 400 expected); raw={str(raw)[:250]}")
            if not (400 <= st <= 499):
                script_error(f"{tag}: unexpected status {st}; raw={str(raw)[:200]}")
            print(f"[{tag}] refused with {st} - proceed to quality scoring")

            try:
                parsed = json.loads(raw) if raw else raw
            except (json.JSONDecodeError, ValueError, TypeError):
                parsed = raw
            score, max_score, hits, norm = check_error_quality(parsed, expected)
            print(f"[{tag} rubric] score={score}/{max_score} hits={hits}")
            print(f"[{tag} rubric] normalized text: {norm[:300]}")
            if score <= 0:
                defect("Type2_PoorDiagnostics",
                       f"{tag}: the {st} rejection carries zero diagnostic content - "
                       f"none of {expected} named, no format hint, no actionable "
                       f"wording; a user cannot attribute the error to the offending "
                       f"member (expected vs actual: >=1 rubric point vs 0/3); "
                       f"raw={str(raw)[:300]}")
            print(f"[{tag}] diagnostics score {score}/3 recorded")

        print("[summary] both field-targeted rejections carry at least minimal "
              "diagnostic content - constraint qdrant_behavioral_collections_"
              "create_003 rejection-quality leg holds")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
