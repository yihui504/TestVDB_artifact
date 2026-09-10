#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_cluster_status_001
# strategy: behavioral_contract
# endpoint: cluster+status
# constraint_ids: qdrant_behavioral_cluster_status_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/cluster-status
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - the documented "valid on single-node
#   deployments" 200 promise vs the disposition actually served on this
#   standalone deployment, where sibling distributed faces refuse with 4xx)
"""
Attack: behavioral_contract x assertions::qdrant_behavioral_cluster_status_001
  (chunk_cluster+status; GET /cluster via runtime path_key cluster_status,
  URL "/cluster" from raw_knowledge api_endpoints[cluster+status].url;
  documented no-body control probe per R7 lesson). The assertion (evidence_tier=
  explicit) promises "HTTP 200 with ClusterStatus even on a single-node
  deployment". Unlike the sibling distributed faces (recover / peer-delete /
  collection-cluster-update) that may legitimately refuse with 4xx "Distributed
  mode disabled" on this standalone deployment (R6/R7 lessons), THIS face is
  explicitly promised reachable + 200 on exactly the deployment class under
  test, so a 4xx refusal here is a broken promise, not a disabled-face
  disposition.
  [chunk_cluster+status coverage: behavioral_contract x
   qdrant_behavioral_cluster_status_001 (single-node 200 promise + envelope
   {status: str, time: num, result: object} + non-empty cluster-info result)]
Oracle: GET /cluster returns exactly HTTP 200 with envelope status being a
  string, time (when present) numeric, and a non-empty result object; a 4xx
  refusal = Type1_IllegalRejection (the bare documented request refused on the
  deployment class the assertion explicitly covers), a 5xx with /healthz alive
  = Type3_RuntimeFailure, another 2xx without/with-empty result object =
  Type4_StateLogicViolation ("with cluster info" half of the promise unmet),
  and the face must still answer 200 on an immediate repeat read.

Rationale (G4/G7): the promise splits into two falsifiable halves - the status
  code (200, not a disabled-refusal 4xx) and the payload (qdrant envelope +
  non-empty cluster-info result node). Both expectations are declared above and
  each observed (status, raw) pair is compared against them explicitly; the
  repeat read guards against a face that serves 200 once then flips.
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

print(f"[path derivation] cluster_status = {rt.PATHS['cluster_status']} "
      f"(raw_knowledge api_endpoints[cluster+status].url)")


def safe_request(method, path_key, body=None, path_params=None, query_params=None,
                timeout=30):
    """All HTTP through the runtime; forwards method/path_key/body/path_params/
    query_params/timeout exactly (standing lesson). Returns (status, raw_text)."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def jload(raw):
    try:
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def script_error(msg):
    print(f"VERDICT: SCRIPT_ERROR - {msg}")
    sys.exit(2)


def defect(dtype, msg):
    print(f"VERDICT: DEFECT_FOUND ({dtype})")
    print(msg)
    sys.exit(1)


def judge_face(st, raw, tag):
    """Judge the documented 200 promise (expected vs actual, per Oracle line)."""
    if st == 0:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[{tag} transport branch] inline /healthz probe status={hs} raw={str(hraw)[:80]}")
        script_error(f"transport failure on GET /cluster (status 0); no defect conclusion")

    if 500 <= st <= 599:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[{tag} 5xx branch] inline /healthz probe status={hs} raw={str(hraw)[:80]}")
        if hs != 200:
            script_error(f"GET /cluster {st} and /healthz {hs}; deployment unstable - no defect conclusion")
        defect("Type3_RuntimeFailure",
               f"GET /cluster raised server error {st} while /healthz is alive; assertion "
               f"qdrant_behavioral_cluster_status_001 promises HTTP 200 (valid on single-node "
               f"deployments), never a 5xx; raw={str(raw)[:200]}")

    if 400 <= st < 500:
        defect("Type1_IllegalRejection",
               f"GET /cluster refused with {st} on a single-node deployment; assertion "
               f"qdrant_behavioral_cluster_status_001 explicitly promises 'HTTP 200 with "
               f"ClusterStatus even on a single-node deployment' (sibling distributed faces "
               f"may refuse when disabled - this one may not); raw={str(raw)[:250]}")

    if not (200 <= st < 300):
        script_error(f"unexpected GET /cluster status {st}; no defect conclusion")

    if st != 200:
        defect("Type4_StateLogicViolation",
               f"GET /cluster answered {st} (not the promised 200) with body "
               f"raw={str(raw)[:200]}; assertion promises 'HTTP 200 with ClusterStatus even "
               f"on a single-node deployment'")


def main():
    hs, hraw = safe_request("GET", "healthz")
    print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
    if hs != 200:
        script_error(f"/healthz pre-probe returned {hs}; deployment not reachable - no defect conclusion")

    # ---- control leg (R7 lesson: documented no-body probe anchors the matrix) ----
    st, raw = safe_request("GET", "cluster_status", timeout=15)
    print(f"[control GET /cluster] status={st} raw={str(raw)[:400]}")
    judge_face(st, raw, "control")

    b = jload(raw)
    if not isinstance(b, dict):
        defect("Type4_StateLogicViolation",
               f"GET /cluster returned 200 but the body is not a JSON object: "
               f"raw={str(raw)[:200]}; the promised '200 with ClusterStatus' face must be "
               f"a qdrant envelope object")

    env_status = b.get("status")
    if not isinstance(env_status, str):
        defect("Type4_StateLogicViolation",
               f"envelope field 'status' missing or not a string (got {env_status!r}); "
               f"qdrant success envelope requires status:str alongside result; "
               f"raw={str(raw)[:250]}")

    env_time = b.get("time")
    if env_time is not None and not (isinstance(env_time, (int, float))
                                     and not isinstance(env_time, bool)):
        defect("Type4_StateLogicViolation",
               f"envelope field 'time' present but not numeric (got {env_time!r}); "
               f"raw={str(raw)[:250]}")

    res = b.get("result")
    if not isinstance(res, dict) or len(res) == 0:
        defect("Type4_StateLogicViolation",
               f"200 answered but the 'cluster info' half of the promise is unmet: result "
               f"node is missing/empty (result={res!r}); assertion promises 'HTTP 200 with "
               f"ClusterStatus even on a single-node deployment'; raw={str(raw)[:250]}")

    # ---- repeat read: the documented face must stay served ----
    st2, raw2 = safe_request("GET", "cluster_status", timeout=15)
    print(f"[repeat GET /cluster] status={st2} raw={str(raw2)[:400]}")
    if st2 == 0:
        hs2, hraw2 = safe_request("GET", "healthz")
        print(f"[repeat transport branch] inline /healthz probe status={hs2} raw={str(hraw2)[:80]}")
        script_error("transport failure on repeat GET /cluster; no defect conclusion")
    if 500 <= st2 <= 599:
        hs2, hraw2 = safe_request("GET", "healthz")
        print(f"[repeat 5xx branch] inline /healthz probe status={hs2} raw={str(hraw2)[:80]}")
        if hs2 != 200:
            script_error(f"repeat GET /cluster {st2} and /healthz {hs2}; deployment unstable")
        defect("Type3_RuntimeFailure",
               f"GET /cluster flipped 200 -> {st2} between two adjacent reads on an idle "
               f"deployment while /healthz is alive; raw={str(raw2)[:200]}")
    if st2 != 200:
        defect("Type4_StateLogicViolation",
               f"the documented 200 face flipped status {st} -> {st2} between two adjacent "
               f"reads on an idle deployment; raw={str(raw2)[:250]}")

    print(f"[summary] GET /cluster served the documented 200 face; envelope OK; "
          f"result keys={sorted(res.keys())}")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
