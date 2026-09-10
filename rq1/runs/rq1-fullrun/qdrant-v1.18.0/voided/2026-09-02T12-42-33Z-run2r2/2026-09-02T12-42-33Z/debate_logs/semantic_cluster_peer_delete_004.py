#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_cluster_peer_delete_004
# strategy: metamorphic
# endpoint: cluster+peer+delete
# constraint_ids: qdrant_behavioral_cluster_peer_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/remove-peer
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - representation-equivalent requests must keep
#   the documented 4xx disposition; a silent flip reveals hidden state or validation drift)
"""
Attack: metamorphic x assertions::qdrant_behavioral_cluster_peer_delete_001
  (chunk_cluster+peer+delete; DELETE /cluster/peer/{peer_id}, URL from raw_knowledge
  api_endpoints[cluster+peer+delete].url). Three disposition-invariance relations on a
  fixed ghost peer id (non-live, so every call must land on the documented "4xx on an
  invalid peer id"):
  R1 (default equivalence): force omitted vs force="false" - the contract documents
      default force=false, so the two spellings are semantically identical requests;
  R2 (rejection idempotency): the identical ghost removal issued twice must keep the
      same disposition class - a later 2xx on the unchanged request would mean the
      first refusal secretly armed/queued the destructive operation (state pollution);
  R3 (irrelevant-parameter isolation): timeout=1 (documented-legal query, min 1) vs
      timeout absent - timeout is a blocking knob, not a validity knob, and must not
      flip the disposition class.
  [chunk_cluster+peer+delete coverage: metamorphic x
   qdrant_behavioral_cluster_peer_delete_001 (disposition invariance leg)]
Oracle: within each relation the two responses share the same disposition class
  ({2xx} / {4xx} / {5xx}); any class divergence = Type4_StateLogicViolation (with the
  2xx-side spelled out in the evidence); a straight 2xx on any leg = Type1_IllegalSuccess;
  5xx with /healthz alive = Type3; status 0 = SCRIPT_ERROR after an inline /healthz probe

Rationale (G6): R2 is the strongest breaker for a destructive endpoint - refused
operations are the only safe ones to repeat, so if repetition alone changes the
answer, rejection is not idempotent and some hidden state (queue, cache, consensus
tentative) survived the refusal. R1/R3 catch default-value and side-parameter drift
that single-shot disposition tests (001) cannot see.
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


def probe(tag, query_params=None):
    """One ghost removal probe; adjudicated immediately (declared expectation:
    4xx). Returns the disposition class label for the relation comparison."""
    st, raw = safe_request("DELETE", REMOVE_PEER_KEY,
                           path_params={"peer_id": GHOST_PEER},
                           query_params=query_params, timeout=15)
    print(f"[{tag}] status={st} raw={str(raw)[:300]}")
    if st == 0:
        liveness("transport")
        script_error(f"transport failure on {tag} (status=0); no defect conclusion")
    if 500 <= st <= 599:
        hs = liveness("5xx")
        if hs != 200:
            script_error(f"5xx on {tag} and /healthz not 200 (={hs}); no defect conclusion")
        defect("Type3_RuntimeFailure",
               f"ghost peer removal on {tag} raised server error {st} while /healthz is alive; "
               f"documented disposition is 4xx; raw={str(raw)[:200]}")
    if 200 <= st < 300:
        defect("Type1_IllegalSuccess",
               f"ghost peer removal on {tag} returned {st} success - the documented disposition "
               f"for a non-live peer id is 4xx (assertion qdrant_behavioral_cluster_peer_delete_001); "
               f"raw={str(raw)[:200]}")
    if 400 <= st < 500:
        return "4xx"
    script_error(f"unexpected status {st} on {tag}; no defect conclusion")


def relation(name, ctx_a, qa, ctx_b, qb):
    """Run both legs, compare disposition classes (declared expectation: equal)."""
    ca = probe(ctx_a, qa)
    cb = probe(ctx_b, qb)
    if ca != cb:
        defect("Type4_StateLogicViolation",
               f"metamorphic relation {name} violated: {ctx_a} -> class {ca} but {ctx_b} -> "
               f"class {cb}; representation-equivalent requests (or an identical repeat) must "
               f"keep the same documented disposition - a flip means hidden state or validation "
               f"drift on DELETE /cluster/peer/{{peer_id}} (assertion qdrant_behavioral_cluster_peer_delete_001)")
    print(f"[relation {name}] invariant holds: both legs -> class {ca}")


def main():
    hs, _ = safe_request("GET", "healthz")
    if hs != 200:
        script_error(f"/healthz pre-probe returned {hs}; deployment not reachable")
    print(f"[pre-probe] /healthz status={hs}")

    relation("R1 default equivalence (force omitted == force=false)",
             "R1a force omitted", None,
             "R1b force=false", {"force": "false"})
    relation("R2 rejection idempotency (identical repeat)",
             "R2a first call", None,
             "R2b identical repeat", None)
    relation("R3 irrelevant-parameter isolation (timeout=1 vs absent)",
             "R3a timeout absent", None,
             "R3b timeout=1 (documented-legal)", {"timeout": 1})

    print("[summary] all three disposition-invariance relations hold on the ghost peer id")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
