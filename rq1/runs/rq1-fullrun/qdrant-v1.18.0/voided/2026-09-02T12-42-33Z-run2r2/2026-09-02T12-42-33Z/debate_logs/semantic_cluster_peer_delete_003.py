#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_cluster_peer_delete_003
# strategy: type_coercion
# endpoint: cluster+peer+delete
# constraint_ids: qdrant_behavioral_cluster_peer_delete_001, qdrant_state_cluster_peer_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/remove-peer
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust - does serde/route extraction silently
#   coerce non-u64 path segments or non-boolean force values instead of rejecting?)
"""
Attack: type_coercion x assertions::qdrant_behavioral_cluster_peer_delete_001 +
  qdrant_state_cluster_peer_delete_001 (chunk_cluster+peer+delete; DELETE
  /cluster/peer/{peer_id}, URL from raw_knowledge api_endpoints[cluster+peer+delete].url).
  The contract types peer_id as integer (u64 path slot) and force as boolean
  (query, default false). Two confusion batteries:
  (a) path slot: alpha string, float, negative, plus-signed, zero-padded, scientific
      notation, hex literal, boolean word, leading whitespace, u64+1 overflow,
      far-overflow decimal - none of these is a valid u64 peer id;
  (b) force query (with a ghost peer id so no real peer can ever be affected):
      "1", "0", "yes", "TRUE", "null", "" - none of these is the documented boolean
      lexical form, and force=true is the consensus-safety bypass, so a coerced
      truthy value would silently arm the destructive flag (the state constraint's
      exact warning).
  [chunk_cluster+peer+delete coverage: type_coercion x
   qdrant_behavioral_cluster_peer_delete_001 (peer_id typing) +
   qdrant_state_cluster_peer_delete_001 (force typing)]
Oracle: every type-confused peer_id form and every non-boolean force value -> HTTP 4xx;
  any 2xx = Type1_IllegalSuccess (coerced acceptance - e.g. "1.5" accepted as 1, or
  force="1" silently coerced to the destructive true), any 5xx with /healthz alive =
  Type3 (a coerced/failed parse must never crash), status 0 = SCRIPT_ERROR after an
  inline /healthz probe

Rationale (G6): the two typed parameters are the endpoint's whole input surface; the
destructive force flag makes its typing safety-critical (constraint: "force bypasses
the safety check"), and the u64 path slot is where untagged serde/route coercion
would show first (BS-01). Same-shape generalization (G3): one coercion quirk (e.g.
"01" -> 1) is only visible as a family pattern across the battery; note "01"/"+1"
can legitimately normalize to a ghost id and then still 4xx on non-existence - only
a 2xx constitutes the coercion defect claim.
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

GHOST_PEER = "987654321987654321"
FACE_UNREACHABLE = "FACE_UNREACHABLE"


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


def classify(status, raw, ctx):
    """Expected: 4xx for every type-confused form. Exits on 2xx/5xx/0; returns
    FACE_UNREACHABLE on 405 (method face not exposed - cannot adjudicate typing)."""
    print(f"[{ctx}] status={status} raw={str(raw)[:300]}")
    if status == 0:
        liveness("transport")
        script_error(f"transport failure on {ctx} (status=0); no defect conclusion")
    if 500 <= status <= 599:
        hs = liveness("5xx")
        if hs != 200:
            script_error(f"5xx on {ctx} and /healthz not 200 (={hs}); no defect conclusion")
        defect("Type3_RuntimeFailure",
               f"type-confused input on {ctx} crashed the endpoint with {status} while /healthz "
               f"is alive - a rejected parse must never surface as a server error; raw={str(raw)[:200]}")
    if 200 <= status < 300:
        defect("Type1_IllegalSuccess",
               f"type confusion accepted on {ctx}: documented types are u64 peer_id / boolean force, "
               f"got {status} success - coercing a malformed path slot or a non-boolean force value "
               f"(the consensus-safety bypass flag) silently changes destructive semantics; "
               f"raw={str(raw)[:200]}")
    if status == 405:
        print(f"OBSERVATION ({ctx}): 405 - the DELETE face is not exposed by this deployment")
        return FACE_UNREACHABLE
    if 400 <= status < 500:
        return True
    script_error(f"unexpected status {status} on {ctx}; no defect conclusion")


def main():
    hs, _ = safe_request("GET", "healthz")
    if hs != 200:
        script_error(f"/healthz pre-probe returned {hs}; deployment not reachable")
    print(f"[pre-probe] /healthz status={hs}")

    path_battery = [
        "not_a_number",       # alpha in u64 slot
        "1.5",                # float
        "-1",                 # negative
        "+1",                 # plus-signed
        "01",                 # zero-padded (may normalize to ghost 1 -> still must 4xx)
        "1e3",                # scientific
        "0x1F",               # hex literal
        "true",               # boolean word in integer slot
        " 7",                 # leading whitespace
        "18446744073709551616",   # u64 + 1
        "999999999999999999999999",  # far overflow
    ]
    force_battery = ["1", "0", "yes", "TRUE", "null", ""]

    refused = 0
    unreachable = 0
    for pid in path_battery:
        st, raw = safe_request("DELETE", REMOVE_PEER_KEY,
                               path_params={"peer_id": pid}, timeout=15)
        outcome = classify(st, raw, f"peer_id={pid!r}")
        if outcome is FACE_UNREACHABLE:
            unreachable += 1
        else:
            refused += 1

    for fv in force_battery:
        st, raw = safe_request("DELETE", REMOVE_PEER_KEY,
                               path_params={"peer_id": GHOST_PEER},
                               query_params={"force": fv}, timeout=15)
        outcome = classify(st, raw, f"force={fv!r} (ghost peer)")
        if outcome is FACE_UNREACHABLE:
            unreachable += 1
        else:
            refused += 1

    if refused == 0:
        script_error("every probe answered 405 - the DELETE peer-removal face is not exposed "
                     "by this deployment; type coercion cannot be adjudicated")
    print(f"[summary] {refused} type-confused forms cleanly refused (4xx), 0 coerced successes")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
