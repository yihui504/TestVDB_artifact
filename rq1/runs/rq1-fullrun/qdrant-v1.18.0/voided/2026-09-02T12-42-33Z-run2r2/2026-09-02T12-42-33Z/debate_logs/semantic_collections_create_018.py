#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_create_018
# strategy: diagnosis_quality
# endpoint: collections+create
# constraint_ids: qdrant_behavioral_collections_create_002
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-02 (Error Message Negligence - generic 'internal error' style
#   rejections for edge cases; the duplicate-name conflict is the classic
#   high-traffic edge whose diagnostics quality is never reviewed)
"""
Attack: diagnosis_quality (Type-2 focused) x
  qdrant_behavioral_collections_create_002 (chunk_collections+create-2of2;
  PUT /collections/{name} via runtime path_key create_collection). The
  assertion leg: duplicate-name create is refused 4xx (409 observed). This
  script scores the QUALITY of that rejection message on the canonical
  3-point rubric: (1) parameter named - for a name collision the
  identifying parameter IS the collection name, so the message must contain
  the actual collection name string; (2) format/range hint - wording that
  indicates the constraint ('already exists', 'must be', 'expected', ...);
  (3) actionable suggestion ('use', 'change', 'try', ...). Declared
  thresholds (oracle-first): score 0/3 = Type2_PoorDiagnostics defect
  (a rejection with zero diagnostic content); score 1-2/3 = NO_DEFECT with
  the score recorded for the auditor (core job done, polish lacking);
  3/3 = NO_DEFECT clean. Prerequisite gate: the duplicate create must
  actually be refused 4xx first (a 200 here is unit 002's Type1 ground and
  is reported as such, not scored).
  [chunk_collections+create-2of2 coverage: diagnosis_quality x
   qdrant_behavioral_collections_create_002 (409-message rubric scoring)]
Oracle: duplicate-name PUT is refused 4xx and its error text scores >= 1/3
  on the rubric (name mentioned / constraint hinted / actionable) - a 4xx
  whose message scores 0/3 = DEFECT_FOUND (Type2_PoorDiagnostics); if the
  duplicate is instead accepted 200 = DEFECT_FOUND (Type1_IllegalSuccess,
  unit 002 ground); 5xx with /healthz alive = Type3_RuntimeFailure;
  otherwise NO_DEFECT with the measured score recorded - constraint
  qdrant_behavioral_collections_create_002.

Rationale (G7/D3a): Type-2 rounds declare the expectation before comparing:
  the rubric and thresholds are fixed in advance so the measured score
  cannot be rationalized after the fact. Body may be JSON or plain text -
  both are normalized to lowercase text before matching.
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

PREFIX = "scc018_"
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


def check_error_quality(body, expected_param):
    """Type-2 diagnosis rubric (canonical 3 points):
    1) parameter named; 2) format/range hint; 3) actionable suggestion.
    body may be dict (JSON) or str (non-JSON) - normalize first."""
    error_msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()
    score = 0
    hits = []
    if expected_param.lower() in error_msg:
        score += 1
        hits.append("param_named")
    format_hints = ["must be", "expected", "should be", "valid", "range",
                    "type", "positive", "non-zero", "already exists", "exists",
                    "duplicate", "conflict"]
    if any(h in error_msg for h in format_hints):
        score += 1
        hits.append("format_hint")
    action_hints = ["correct", "try", "use", "change", "specify", "provide",
                    "delete", "choose", "another"]
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
        name = mkn("diag")
        body = {"vectors": {"size": 4, "distance": "Cosine"}}
        st, raw = safe_request("PUT", "create_collection", body,
                               path_params={"name": name})
        print(f"[create-original {name}] status={st} raw={str(raw)[:300]}")
        if st not in (200, 201):
            script_error(f"original create failed with {st}; setup unavailable; raw={str(raw)[:200]}")
        CREATED.append(name)

        # the unit's rejection leg
        st2, raw2 = safe_request("PUT", "create_collection", body,
                                 path_params={"name": name})
        print(f"[duplicate] status={st2} raw={str(raw2)[:400]}")
        if st2 == 0:
            if liveness("transport") != 200:
                script_error("transport failure and /healthz down; no defect conclusion")
            script_error("transport failure; /healthz alive; no defect conclusion")
        if 500 <= st2 <= 599:
            if liveness("5xx") != 200:
                script_error(f"duplicate create 5xx ({st2}) and /healthz not 200; deployment unstable")
            defect("Type3_RuntimeFailure",
                   f"duplicate-name create raised {st2} while /healthz alive; raw={str(raw2)[:200]}")
        if st2 in (200, 201):
            defect("Type1_IllegalSuccess",
                   f"duplicate create accepted with {st2} (unit 002 ground: 4xx expected, "
                   f"never 200); raw={str(raw2)[:250]}")
        if not (400 <= st2 <= 499):
            script_error(f"duplicate create returned unexpected status {st2}; raw={str(raw2)[:200]}")
        print(f"[gate] duplicate refused with {st2} (4xx family) - proceed to quality scoring")

        try:
            parsed = json.loads(raw2) if raw2 else raw2
        except (json.JSONDecodeError, ValueError, TypeError):
            parsed = raw2
        score, max_score, hits, norm = check_error_quality(parsed, name)
        print(f"[rubric] score={score}/{max_score} hits={hits}")
        print(f"[rubric] normalized message text: {norm[:300]}")
        if score <= 0:
            defect("Type2_PoorDiagnostics",
                   f"duplicate-name rejection ({st2}) carries zero diagnostic content: "
                   f"the collection name {name!r} is absent, no constraint hint, no "
                   f"actionable wording; raw={str(raw2)[:300]} (expected vs actual: "
                   f">=1 rubric point vs 0/3)")
        print(f"[verdict-input] rejection diagnostics score {score}/3 "
              f"({', '.join(hits) if hits else 'none'}) - threshold 0/3 for a "
              f"Type2 defect; >=1 passes with the score recorded")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
