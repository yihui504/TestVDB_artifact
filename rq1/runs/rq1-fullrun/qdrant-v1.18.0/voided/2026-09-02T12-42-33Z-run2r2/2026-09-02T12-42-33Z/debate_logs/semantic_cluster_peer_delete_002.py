#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_cluster_peer_delete_002
# strategy: diagnosis_quality
# endpoint: cluster+peer+delete
# constraint_ids: qdrant_behavioral_cluster_peer_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/remove-peer
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-02 (Error Message Negligence - the 4xx-on-invalid-peer-id promise is only
#   useful if the rejection lets the caller identify the offending parameter)
"""
Attack: diagnosis_quality (Type-2) x assertions::qdrant_behavioral_cluster_peer_delete_001
  (chunk_cluster+peer+delete; DELETE /cluster/peer/{peer_id}, URL from raw_knowledge
  api_endpoints[cluster+peer+delete].url). The assertion documents "an invalid peer id
  returns a 4xx error"; this script scores the QUALITY of those rejections on the
  3-point rubric (parameter named + format/range hint + actionable suggestion) over a
  battery of invalid peer-id forms: one well-formed ghost u64, one alpha string, one
  float, one u64-overflow value. Mode-gated refusals (e.g. "Distributed mode disabled")
  are scored exactly as observed - if the observable rejection for an invalid peer id
  names neither the parameter nor any corrective hint, the caller cannot tell a bad id
  from a bad deployment, which is the BS-02 diagnostics gap.
  [chunk_cluster+peer+delete coverage: diagnosis_quality x
   qdrant_behavioral_cluster_peer_delete_001 (rejection diagnostics leg)]
Oracle: every invalid peer-id form -> 4xx and the BEST rejection message in the battery
  scores >= 2/3 on the diagnosis rubric (at minimum the parameter subject 'peer' plus a
  format or actionable hint); all-4xx with best score <= 1/3 = Type2_PoorDiagnostics,
  any 2xx = Type1_IllegalSuccess (diagnostics moot), any 5xx with /healthz alive =
  Type3, status 0 = SCRIPT_ERROR after an inline /healthz probe

Rationale (G7): the rubric criteria are fixed before execution and each criterion is
independently greppable in the printed raw responses, so the judge can re-derive every
score. Param-naming is scored conservatively: any mention of "peer" (not only the
literal "peer_id") earns the point, which biases against a defect claim.
"""

import os
import sys
import json
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

# ---- runtime PATHS gap: register the contract-derived URL (same as 001) ----
REMOVE_PEER_KEY = "remove_peer"
if REMOVE_PEER_KEY not in rt.PATHS:
    rt.PATHS[REMOVE_PEER_KEY] = "/cluster/peer/{peer_id}"
print(f"[path derivation] remove_peer = {rt.PATHS[REMOVE_PEER_KEY]} (raw_knowledge api_endpoints[cluster+peer+delete].url)")

EXPECTED_PARAM = "peer_id"


def safe_request(method, path_key, path_params=None, body=None, query_params=None,
                 timeout=30):
    """All HTTP through the runtime; kept in this exact call form so the inline
    liveness probes (GET healthz) stay visible to static checks. timeout is
    forwarded to rt.request (per-request transport timeout)."""
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
    hs, hraw = safe_request("GET", "healthz")
    print(f"[{tag}] /healthz probe status={hs} raw={str(hraw)[:120]}")
    return hs


def error_message(body, raw):
    """Extract the human-readable error text: qdrant error envelope
    {"status":{"error":...}} first, then any string body (rubric operates on text)."""
    if isinstance(body, dict):
        st = body.get("status")
        if isinstance(st, dict) and isinstance(st.get("error"), str):
            return st["error"]
        if isinstance(body.get("error"), str):
            return body["error"]
    return str(raw)


def check_error_quality(error_msg, expected_param):
    """Type-2 diagnosis quality rubric (strategy 2):
    - Criterion 1 (parameter named): literal param name, or conservatively any
      mention of the parameter subject 'peer'
    - Criterion 2 (format/range hint)
    - Criterion 3 (actionable suggestion)
    Returns (score, detail list)."""
    m = (error_msg or "").lower()
    score = 0
    detail = []

    named = expected_param.lower() in m or "peer" in m
    if named:
        score += 1
    detail.append(f"param_named={named}")

    format_hints = ["must be", "expected", "should be", "valid", "range", "type",
                    "positive", "non-zero", "integer", "uint64", "parse", "format"]
    fmt = any(h in m for h in format_hints)
    if fmt:
        score += 1
    detail.append(f"format_hint={fmt}")

    action_hints = ["correct", "try", "use", "change", "specify", "provide",
                    "enable", "start", "remove"]
    act = any(h in m for h in action_hints)
    if act:
        score += 1
    detail.append(f"actionable={act}")
    return score, detail


def main():
    hs, _ = safe_request("GET", "healthz")
    if hs != 200:
        script_error(f"/healthz pre-probe returned {hs}; deployment not reachable")
    print(f"[pre-probe] /healthz status={hs}")

    battery = [
        ("987654321987654321", "well-formed ghost u64"),
        ("not_a_number", "alpha string in u64 path slot"),
        ("1.5", "float in u64 path slot"),
        ("18446744073709551616", "u64+1 overflow value"),
    ]

    rows = []
    unreachable = 0
    for pid, desc in battery:
        st, raw = safe_request("DELETE", REMOVE_PEER_KEY,
                               path_params={"peer_id": pid}, timeout=15)
        print(f"[{desc}] status={st} raw={str(raw)[:300]}")
        if st == 0:
            liveness("transport")
            script_error(f"transport failure probing '{pid}' (status=0); no defect conclusion")
        if 500 <= st <= 599:
            h = liveness("5xx")
            if h != 200:
                script_error(f"5xx probing '{pid}' and /healthz not 200 (={h}); no defect conclusion")
            defect("Type3_RuntimeFailure",
                   f"invalid peer id '{pid}' ({desc}) raised server error {st} while /healthz is "
                   f"alive; documented disposition is 4xx; raw={str(raw)[:200]}")
        if 200 <= st < 300:
            defect("Type1_IllegalSuccess",
                   f"invalid peer id '{pid}' ({desc}) accepted with {st}; assertion promises 4xx - "
                   f"diagnostics are moot when the invalid id is not rejected at all; raw={str(raw)[:200]}")
        if st == 405:
            unreachable += 1
            continue
        if not (400 <= st < 500):
            script_error(f"unexpected status {st} probing '{pid}'; no defect conclusion")
        try:
            body = json.loads(raw) if raw else raw
        except (json.JSONDecodeError, ValueError, TypeError):
            body = raw
        msg = error_message(body, raw)
        score, detail = check_error_quality(msg, EXPECTED_PARAM)
        rows.append((desc, st, msg, score, detail))
        print(f"  rubric: score={score}/3 ({', '.join(detail)}) on message={msg!r}")

    if not rows:
        script_error("every probe answered 405 - the DELETE peer-removal face is not exposed "
                     "by this deployment; rejection diagnostics cannot be adjudicated")

    best = max(r[3] for r in rows)
    print(f"[rubric table] best score in battery = {best}/3 over {len(rows)} scored rejections")
    if best <= 1:
        defect("Type2_PoorDiagnostics",
               f"all invalid-peer-id rejections on DELETE /cluster/peer/{{peer_id}} score <= 1/3 on the "
               f"diagnosis rubric (best={best}/3): no rejection names the parameter subject 'peer' "
               f"together with a format or actionable hint, so a caller cannot distinguish a bad "
               f"peer id from any other refusal cause; assertion qdrant_behavioral_cluster_peer_delete_001 "
               f"documents '4xx on an invalid peer id' - the 4xx is delivered but undiagnosable")
    print(f"[summary] {len(rows)} scored 4xx rejections; best rubric score {best}/3 >= 2/3")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
