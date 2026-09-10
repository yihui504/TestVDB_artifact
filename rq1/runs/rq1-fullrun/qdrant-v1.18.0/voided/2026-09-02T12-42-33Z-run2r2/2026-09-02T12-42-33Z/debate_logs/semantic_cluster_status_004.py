#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_cluster_status_004
# strategy: diagnosis_quality
# endpoint: cluster+status
# constraint_ids: qdrant_type_cluster_status_001, qdrant_behavioral_cluster_status_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/cluster-status
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-02 (Error Message Negligence - generic/empty refusal bodies on
#   the error faces of a documented endpoint) + BS-01 (Parameter Type Coercion
#   Trust - undocumented query params with hostile-typed values must not
#   perturb the status face)
"""
Attack: diagnosis_quality x cluster+status error faces (chunk_cluster+status;
  the same URL "/cluster" from raw_knowledge api_endpoints[cluster+status].url,
  attacked through its undocumented method/parameter faces; documented no-body
  control probes bracket every matrix leg, per R7 lesson). raw_knowledge
  documents exactly one face for this URL: GET /cluster, parameters=[] .
  Error-face matrix:
    L1-L3 method confusion: POST /cluster (empty body), PUT /cluster (junk
        body), DELETE /cluster - none is a documented operation on this URL;
        each must be refused with a clean 4xx whose body carries at least one
        rubric element (method/problem named, format hint, or actionable hint);
    L4 undocumented query params with hostile-typed values on the
        parameterless GET (peer_id=abc, raft_state=NotAState,
        commit_index=-5): acceptable dispositions are 200 with the result node
        bit-identical to the control (params ignored) or a clean 4xx with
        diagnostics;
    residue control: after the whole matrix the plain GET must still answer
        200 with the unchanged result node (a refused-method matrix must leave
        zero trace on the face - G9 consistent disposition).
  [chunk_cluster+status coverage: diagnosis_quality (Type2 rubric) x
   cluster+status endpoint error faces (method confusion + undocumented
   query-param disposition); anchored on both chunk units - the type
   constraint fixes the result-node semantics used for the no-change check,
   the behavioral assertion fixes the 200 control that brackets the matrix)]
Oracle: every method-confusion leg answers 4xx (2xx = Type1_IllegalSuccess -
  an undocumented mutating method executed on a GET-only documented face;
  5xx with /healthz alive = Type3) and each 4xx body scores >= 1 on the Type2
  rubric (problem-named + format-hint + actionable-hint; score 0 = an opaque
  empty/generic body = Type2_PoorDiagnostics); the query-param leg answers
  200 with a result node identical to the control (a changed result node =
  Type4: undocumented params perturbed the status face) or a rubric-scored
  4xx; the final control still answers 200 with the unchanged result node
  (any residue = Type4).

Rationale (G6/G9): method confusion and hostile-typed undocumented params are
  the only mutable inputs a parameterless GET face exposes; they are exactly
  the inputs a misconfigured reverse proxy / SDK bug would send in production,
  so the refusal bodies' diagnostic quality (BS-02) and the face's immunity to
  undocumented inputs (BS-01) are the decisive falsifiable properties. The
  control-before/control-after bracket converts the matrix into a state
  assertion, not just a status snapshot.
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


def check_error_quality(raw, expected_terms):
    """Type-2 diagnosis quality rubric (spec strategy 2): 1pt any expected
    problem-term named, 1pt format/range hint, 1pt actionable hint. The body
    may be a JSON object, a plain string, or empty."""
    msg = raw.lower() if isinstance(raw, str) else json.dumps(raw).lower()
    score = 0
    if any(t.lower() in msg for t in expected_terms):
        score += 1
    format_hints = ["must be", "expected", "should be", "valid", "range", "type",
                    "positive", "non-zero", "allowed", "supported", "method",
                    "parameter", "unknown"]
    if any(h in msg for h in format_hints):
        score += 1
    action_hints = ["correct", "try", "use", "change", "specify", "provide",
                    "refer", "documentation"]
    if any(h in msg for h in action_hints):
        score += 1
    return score


def script_error(msg):
    print(f"VERDICT: SCRIPT_ERROR - {msg}")
    sys.exit(2)


def defect(dtype, msg):
    print(f"VERDICT: DEFECT_FOUND ({dtype})")
    print(msg)
    sys.exit(1)


def control_read(tag):
    """Documented no-body control probe: GET /cluster must answer 200 with a
    result object. Returns the canonical result-node string."""
    st, raw = safe_request("GET", "cluster_status", timeout=15)
    print(f"[{tag} control GET /cluster] status={st} raw={str(raw)[:300]}")
    if st == 0:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[{tag} transport branch] inline /healthz probe status={hs} raw={str(hraw)[:80]}")
        script_error(f"transport failure on control GET /cluster ({tag}); no defect conclusion")
    if 500 <= st <= 599:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[{tag} 5xx branch] inline /healthz probe status={hs} raw={str(hraw)[:80]}")
        if hs != 200:
            script_error(f"control GET /cluster {st} and /healthz {hs}; deployment unstable")
        defect("Type3_RuntimeFailure",
               f"plain GET /cluster raised {st} during the {tag} leg while /healthz is "
               f"alive; raw={str(raw)[:200]}")
    if st != 200:
        script_error(f"control GET /cluster answered {st} at {tag}; the documented face "
                     "must be served for its error faces to be judged (200-promise "
                     "owned by semantic_cluster_status_001)")
    b = jload(raw)
    res = b.get("result") if isinstance(b, dict) else None
    if not isinstance(res, dict):
        script_error(f"control GET /cluster 200 without a result object at {tag}; owned by "
                     "semantic_cluster_status_001")
    return json.dumps(res, sort_keys=True)


def judge_leg(tag, st, raw, terms):
    """One matrix leg: 4xx + rubric, 2xx = illegal success, 5xx = Type3."""
    if st == 0:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[{tag} transport branch] inline /healthz probe status={hs} raw={str(hraw)[:80]}")
        script_error(f"transport failure on {tag}; no defect conclusion")
    if 500 <= st <= 599:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[{tag} 5xx branch] inline /healthz probe status={hs} raw={str(hraw)[:80]}")
        if hs != 200:
            script_error(f"{tag} returned {st} and /healthz {hs}; deployment unstable")
        defect("Type3_RuntimeFailure",
               f"{tag} raised server error {st} while /healthz is alive; raw={str(raw)[:200]}")
    if 200 <= st < 300:
        defect("Type1_IllegalSuccess",
               f"{tag} was EXECUTED (status {st}) - raw_knowledge documents exactly one "
               f"face for /cluster (GET, parameters=[]) and no such operation; an "
               f"undocumented mutating method ran on a GET-only documented face "
               f"(G9); raw={str(raw)[:250]}")
    if 400 <= st < 500:
        score = check_error_quality(raw, terms)
        print(f"[{tag} rubric] 4xx refusal status={st} rubric_score={score}/3 raw={str(raw)[:300]}")
        if score == 0:
            defect("Type2_PoorDiagnostics",
                   f"{tag} refused with {st} but the body carries none of the rubric "
                   f"elements (problem named / format hint / actionable hint) - an opaque "
                   f"refusal body leaves the caller unable to tell a wrong method from a "
                   f"broken deployment; raw={str(raw)[:250]}")
        return score
    script_error(f"{tag} answered unexpected status {st}; no defect conclusion")
    return 0


def main():
    hs, hraw = safe_request("GET", "healthz")
    print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
    if hs != 200:
        script_error(f"/healthz pre-probe returned {hs}; deployment not reachable")

    baseline = control_read("pre-matrix")

    scores = {}
    # ---- L1-L3: method confusion on the GET-only documented URL ----
    for method, body, tag in (
        ("POST", {}, "L1 POST /cluster (empty body)"),
        ("PUT", {"peer_id": "x"}, "L2 PUT /cluster (junk body)"),
        ("DELETE", None, "L3 DELETE /cluster"),
    ):
        control_read(f"bracket-{tag.split()[0]}")
        st, raw = safe_request(method, "cluster_status", body=body, timeout=15)
        print(f"[{tag}] status={st} raw={str(raw)[:300]}")
        scores[tag] = judge_leg(tag, st, raw, [method, "method", "get"])

    # ---- L4: hostile-typed undocumented query params on the parameterless GET ----
    control_read("bracket-L4")
    st, raw = safe_request("GET", "cluster_status",
                           query_params={"peer_id": "abc", "raft_state": "NotAState",
                                         "commit_index": "-5"},
                           timeout=15)
    print(f"[L4 GET /cluster?peer_id=abc&raft_state=NotAState&commit_index=-5] "
          f"status={st} raw={str(raw)[:400]}")
    if st == 0:
        hs2, hraw2 = safe_request("GET", "healthz")
        print(f"[L4 transport branch] inline /healthz probe status={hs2} raw={str(hraw2)[:80]}")
        script_error("transport failure on L4; no defect conclusion")
    if 500 <= st <= 599:
        hs2, hraw2 = safe_request("GET", "healthz")
        print(f"[L4 5xx branch] inline /healthz probe status={hs2} raw={str(hraw2)[:80]}")
        if hs2 != 200:
            script_error(f"L4 returned {st} and /healthz {hs2}; deployment unstable")
        defect("Type3_RuntimeFailure",
               f"undocumented query params (peer_id=abc, raft_state=NotAState, "
               f"commit_index=-5) crashed the status face with {st} while /healthz is "
               f"alive; the face documents parameters=[] and must ignore or cleanly "
               f"reject unknown inputs; raw={str(raw)[:250]}")
    if 200 <= st < 300:
        b = jload(raw)
        res = b.get("result") if isinstance(b, dict) else None
        got = json.dumps(res, sort_keys=True) if isinstance(res, dict) else None
        if got is None or got != baseline:
            defect("Type4_StateLogicViolation",
                   "undocumented query params CHANGED the served status face: baseline "
                   f"result={baseline[:250]} vs L4 result={str(got)[:250]} (status {st}); "
                   "the face documents parameters=[] - unknown params must have no "
                   "behavioral effect")
        print("[L4] 200 with result identical to control - unknown params ignored (OK)")
    elif 400 <= st < 500:
        scores["L4 query params"] = judge_leg(
            "L4 query params", st, raw, ["peer_id", "raft_state", "commit_index",
                                         "parameter", "unknown"])
    else:
        script_error(f"L4 answered unexpected status {st}; no defect conclusion")

    # ---- residue control: the matrix must leave zero trace on the face ----
    final = control_read("post-matrix")
    if final != baseline:
        defect("Type4_StateLogicViolation",
               "the refused-method/param matrix left residue on the status face: "
               f"baseline result={baseline[:250]} vs post-matrix result={final[:250]} - "
               "every leg was refused (4xx), so the face must be bit-identical (G9)")

    print(f"[summary] matrix refused cleanly on all legs; rubric scores={scores}")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
