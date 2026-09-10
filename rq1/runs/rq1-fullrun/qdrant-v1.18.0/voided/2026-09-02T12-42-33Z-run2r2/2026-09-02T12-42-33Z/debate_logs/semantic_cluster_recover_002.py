#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_cluster_recover_002
# strategy: diagnosis_quality
# endpoint: cluster+recover
# constraint_ids: qdrant_behavioral_cluster_recover_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/recover-current-peer
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-02 (Error Message Negligence - generic/empty refusal bodies on
#   edge-case faces leave the operator unable to tell "wrong deployment mode" from
#   "wrong endpoint")
"""
Attack: diagnosis_quality (Strategy 2, Type-2 focused) x
  assertions::qdrant_behavioral_cluster_recover_001 (chunk_cluster+recover; POST
  /cluster/recover, URL from raw_knowledge api_endpoints[cluster+recover].url).
  The assertion documents a success face ("returns 200 ok ... only when quorum is
  permanently lost"); on this standalone deployment the face is expected to be
  refused (R6 lesson: distributed faces refuse with 4xx "Distributed mode
  disabled"). G5 types that outcome as "rejects with clear diagnostics = not a
  defect" - so the falsifiable property of THIS script is the diagnostic itself:
  the refusal body must at minimum (a) be non-empty and (b) name the capability
  that is unavailable (cluster/distributed/recover/peer/raft/mode terms). A bare
  status code with an empty or fully generic body ("error"/"internal error" with
  no face term) is a Type2_PoorDiagnostics defect per the 3-criterion rubric
  (face_named + hint + actionable; parameter_named is void here - the endpoint
  documents no request parameter besides the api-key header). The sibling face
  GET /cluster is probed for diagnostic consistency (G9): both faces belong to
  the same disabled capability and should both carry the diagnostic.
  [chunk_cluster+recover coverage: diagnosis_quality x
   qdrant_behavioral_cluster_recover_001 (refusal diagnostic quality + sibling
   face consistency)]
Oracle: POST /cluster/recover on the disabled face -> 4xx whose body is non-empty
  AND contains at least one capability term (cluster|distributed|recover|peer|raft|
  consensus|mode) => NO_DEFECT (score breakdown printed); 4xx with empty body or a
  generic body scoring 0 on face_named => DEFECT Type2_PoorDiagnostics; 5xx with
  /healthz alive => Type3_RuntimeFailure (crash outranks diagnostics); 2xx =>
  premise void (documented success face served on standalone) => honest
  SCRIPT_ERROR, diagnostics not judgeable
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

# ---- runtime PATHS gap: register the contract-derived URL (raw_knowledge only) ----
RECOVER_KEY = "recover_peer"
if RECOVER_KEY not in rt.PATHS:
    rt.PATHS[RECOVER_KEY] = "/cluster/recover"
print(f"[path derivation] recover_peer = {rt.PATHS[RECOVER_KEY]} (raw_knowledge api_endpoints[cluster+recover].url)")


def safe_request(method, path_key, body=None, path_params=None, query_params=None,
                timeout=30):
    """All HTTP through the runtime; kept in this exact call form so the inline
    liveness probes (GET healthz) stay visible to static checks. timeout is
    forwarded to rt.request (per-request transport timeout)."""
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
    hs, hraw = safe_request("GET", "healthz")
    print(f"[{tag}] /healthz probe status={hs} raw={str(hraw)[:120]}")
    return hs


# ---- Type-2 rubric (adapted to a face-class refusal; param_named is void:
#      the endpoint documents no request parameter besides the api-key header) ----
FACE_TERMS = ["cluster", "distributed", "recover", "peer", "raft", "consensus", "mode"]
HINT_TERMS = ["disabled", "not enabled", "enabled", "mode", "unavailable", "standalone",
              "required", "must", "only", "quorum", "deployment", "single-node"]
ACTION_TERMS = ["enable", "start", "use", "set", "configure", "restart", "deploy",
                "check", "refer", "documentation", "qdrant__cluster"]


def score_diagnostic(raw):
    """3-criterion rubric on the refusal body: face_named + hint + actionable.
    body may be JSON (use 'description'/'message'/'error' + full text) or plain."""
    b = jload(raw)
    text = str(raw).lower()
    if isinstance(b, dict):
        for k in ("description", "message", "error", "details"):
            v = b.get(k)
            if isinstance(v, str) and v.strip():
                text = f"{text} {v.lower()}"
    score = {"face_named": 0, "hint": 0, "actionable": 0}
    if any(t in text for t in FACE_TERMS):
        score["face_named"] = 1
    if any(t in text for t in HINT_TERMS):
        score["hint"] = 1
    if any(t in text for t in ACTION_TERMS):
        score["actionable"] = 1
    return score, text.strip()


def face_guard():
    """R6 lesson: probe the deployment face first; judge only the falsifiable
    status class; exit honestly otherwise."""
    st, raw = safe_request("GET", "cluster_status", timeout=15)
    print(f"[face probe GET /cluster] status={st} raw={str(raw)[:300]}")
    if st == 0:
        liveness("transport")
        script_error("transport failure probing GET /cluster; no defect conclusion")
    if 500 <= st <= 599:
        hs = liveness("5xx")
        if hs != 200:
            script_error(f"GET /cluster 5xx ({st}) and /healthz {hs}; deployment unstable")
        script_error(f"GET /cluster 5xx ({st}) with /healthz alive; face state unknown - no falsifiable leg")
    if 200 <= st < 300:
        print("SKIPPED: POST /cluster/recover on a live distributed deployment - sibling constraint "
              "qdrant_state_cluster_recover_001 marks recovery as destructive for cluster membership "
              "(by-design per threat_model); exercising it needs a disposable cluster")
        script_error("distributed deployment detected (GET /cluster 200); destructive recover face "
                     "not exercisable on the shared deployment; honest exit (R6 lesson)")
    if 400 <= st < 500:
        return True
    script_error(f"unexpected GET /cluster status {st}; no defect conclusion")


def main():
    hs, _ = safe_request("GET", "healthz")
    if hs != 200:
        script_error(f"/healthz pre-probe returned {hs}; deployment not reachable")
    print(f"[pre-probe] /healthz status={hs}")
    face_guard()

    # ---- the refusal under test ----
    st, raw = safe_request("POST", RECOVER_KEY, timeout=20)
    print(f"[POST /cluster/recover] status={st}")
    print(raw)

    if st == 0:
        liveness("transport")
        script_error("transport failure on POST /cluster/recover; no defect conclusion")
    if 500 <= st <= 599:
        hs = liveness("5xx")
        if hs != 200:
            script_error(f"5xx on recover and /healthz not 200 (={hs}); no defect conclusion")
        defect("Type3_RuntimeFailure",
               f"POST /cluster/recover raised {st} while /healthz is alive - the crash outranks "
               f"any diagnostics judgement (assertion qdrant_behavioral_cluster_recover_001 "
               f"documents 200, never a crash); raw={str(raw)[:200]}")
    if 200 <= st < 300:
        script_error("premise void: POST /cluster/recover returned 2xx on this standalone "
                     "deployment (the documented success face was served); refusal-diagnostic "
                     "quality is not judgeable - the disposition question is owned by "
                     "semantic_cluster_recover_001")
    if not (400 <= st < 500):
        script_error(f"unexpected recover status {st}; no defect conclusion")

    score, text = score_diagnostic(raw)
    print(f"[rubric] face_named={score['face_named']} hint={score['hint']} "
          f"actionable={score['actionable']} body={text[:200]}")

    # ---- sibling face for G9 diagnostic consistency (evidence, not a defect leg) ----
    sst, sraw = safe_request("GET", "cluster_status", timeout=15)
    sscore, _ = score_diagnostic(sraw)
    print(f"[sibling GET /cluster] status={sst} rubric={sscore} raw={str(sraw)[:300]}")
    if score["face_named"] == 1 and sscore["face_named"] == 0:
        print("OBSERVATION (G9): recover face names the capability but the sibling /cluster "
              "face does not - inconsistent diagnostics across one disabled capability")

    if score["face_named"] == 0:
        defect("Type2_PoorDiagnostics",
               f"POST /cluster/recover refused with {st} but the diagnostic does not name the "
               f"unavailable capability (no cluster/distributed/recover/peer/raft/mode term; "
               f"rubric face_named=0 hint={score['hint']} actionable={score['actionable']}) - "
               f"BS-02: the operator cannot tell 'wrong deployment mode' from 'wrong endpoint'; "
               f"raw={str(raw)[:200]}")
    print(f"[summary] refusal carries a face-naming diagnostic (score={score}); "
          f"hint/actionable breakdown recorded above")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
