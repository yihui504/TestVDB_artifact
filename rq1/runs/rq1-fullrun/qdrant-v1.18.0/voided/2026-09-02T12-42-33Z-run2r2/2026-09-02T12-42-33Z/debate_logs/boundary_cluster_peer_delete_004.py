#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-confusion attack on the optional QUERY PARAMETER `force`
  (boolean, default false) of cluster+peer+delete (DELETE /cluster/peer/{peer_id})
  x qdrant_behavioral_cluster_peer_delete_001, probed against a runtime-derived
  nonexistent peer id. Non-canonical boolean spellings:
    TRUE | True | yes | 1 | 0 | 2 | "" (empty) | null
  plus canonical controls force=true / force=false (must parse cleanly), and
  non-numeric timeout spellings timeout=abc / timeout=1.5 (query-side type
  confusion on the sibling query param).
  Placement check (v34 R1 lesson): force and timeout are in:QUERY -> params= only.
  [chunk_cluster+peer+delete coverage: strategy2 type-confusion x
   qdrant_behavioral_cluster_peer_delete_001 — force/timeout query-type face]
Oracle: every probe returns 4xx (non-canonical bool/int spellings rejected at
  deserialization, or the nonexistent peer id rejected per the assertion's 4xx
  face — both qualify); canonical controls also land in 4xx on this standalone
  deployment (no peer exists), giving the disposition contrast; any 2xx =
  Type1_IllegalSuccess (a type-confused query value coerced AND a removal
  declared successful on an invalid peer id); 5xx = Type3_RuntimeFailure with
  /healthz rechecked; transport failure with healthy /healthz = SCRIPT_ERROR;
  discovery failure = SCRIPT_ERROR. Strategy-5 soft assessment: rejection bodies
  are printed and annotated when they name the offending parameter — recorded as
  judge-facing diagnostics evidence only (no claim: error-field naming is not
  contract per the threat model's by-design list).
Constraint: qdrant_behavioral_cluster_peer_delete_001
Blindspot: BS-01 Parameter Type Coercion Trust (boolean query param assumed
  strictly parsed; "TRUE"/"yes"/"1" may coerce to true in lenient parsers)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/remove-peer
doc_version: 1.18.x (versioned v-1-18-x api-reference)

Contract-driven route derivation (R4/R5 lesson: the chunk label is NOT a route):
  raw_knowledge.api_endpoints[]: path="cluster+peer+delete", method="DELETE",
  url="/cluster/peer/{peer_id}", parameters: force (boolean, query, default
  false), timeout (integer, query, min 1). Reachability probe FIRST (R5):
  GET /cluster; probe peer id DERIVED at runtime (max(discovered)+1 or uuid-derived)
  and never a discovered real peer. force=true is a DESTRUCTIVE flag (state
  constraint qdrant_state_cluster_peer_delete_001) — it is only ever sent against
  the derived nonexistent id, so no real peer can be removed by this script.
"""

import json
import os
import sys
import uuid
from pathlib import Path

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# --- X1 bootstrap: three-layer fallback (env -> upward walk -> contract target) ---
BASE_URL = os.environ.get("TESTVDB_DB_URL")
TARGET = os.environ.get("TESTVDB_TARGET", "")
if not TARGET:
    _root = Path(__file__).resolve()
    for _p in (_root, *list(_root.parents)):
        _f = _p / "structured_contract.json"
        if _f.exists():
            try:
                _c = json.loads(_f.read_text(encoding="utf-8"))
                TARGET = _c.get("target", "") or TARGET
            except Exception:
                pass
            break
if not BASE_URL or TARGET != "qdrant":
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL/TESTVDB_TARGET missing (bootstrap fallback failed)")
    sys.exit(2)

AUTH_HEADER = os.environ.get("TESTVDB_AUTH_HEADER", "")


def safe_request(method, endpoint, json=None, params=None, data=None, timeout=10):
    """
    Safe HTTP request wrapper with unified error handling (agents/_target_api_reference.md).
    Returns: (status_code, body, raw_text)
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    if AUTH_HEADER:
        headers["Authorization"] = AUTH_HEADER
    try:
        response = requests.request(
            method=method, url=url, json=json, params=params,
            data=data, headers=headers, timeout=timeout,
        )
        status_code = response.status_code
        raw_text = response.text
        try:
            body = response.json()
        except Exception:
            body = raw_text
        return status_code, body, raw_text
    except Exception as e:
        return -1, str(e), str(e)


def healthz_ladder(label):
    """G8 liveness re-check: Type3 verdict string if the service is down, else None."""
    hs, _, hraw = safe_request("GET", "/healthz", timeout=5)
    print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
    if hs <= 0 or hs >= 500:
        return (f"DEFECT_FOUND (Type3_RuntimeFailure) — probe '{label}' transport "
                f"failure and /healthz={hs} (service down)")
    return None


def discover_cluster():
    """GET /cluster reachability probe (R5). Returns (cluster_status, known_ids) or None."""
    s, _, raw = safe_request("GET", "/cluster", timeout=15)
    print(f"[discover GET /cluster] status={s} raw={str(raw)[:200]}")
    if s <= 0:
        if healthz_ladder("GET /cluster discovery") is not None:
            return "DOWN", set()
        return None
    known = set()
    status_text = ""
    try:
        node = json.loads(raw).get("result")
        if isinstance(node, dict):
            status_text = str(node.get("status", ""))
            if isinstance(node.get("peer_id"), int):
                known.add(node["peer_id"])
            peers = node.get("peers")
            if isinstance(peers, dict):
                for p in peers.keys():
                    if str(p).isdigit():
                        known.add(int(p))
    except Exception:
        pass
    print(f"[discover] cluster status={status_text!r} known_peer_ids={sorted(known)}")
    return status_text, known


def derive_ghost_id(known):
    """Derive a guaranteed-nonexistent peer id at runtime (no hardcode; R5 lesson)."""
    if known:
        return max(known) + 1
    return (uuid.uuid4().int >> 2) & 0x7FFFFFFFFFFFFFFF


# Declare-first oracle (G7): type-confused query values must not reach a 2xx.
def judge_probe(label, status, raw):
    """Declare-first adjudication ladder for one probe. Returns verdict string or None."""
    if status <= 0:
        v = healthz_ladder(label)
        if v is not None:
            return v
        return "SCRIPT_ERROR — transport failure with healthy /healthz (no defect conclusion)"
    if 500 <= status <= 599:
        v = healthz_ladder(label)
        if v is not None:
            return v
        return (f"DEFECT_FOUND (Type3_RuntimeFailure) — probe '{label}' got {status} "
                f"with /healthz alive; body: {str(raw)[:200]}")
    if 400 <= status < 500:
        return None  # 4xx satisfies the oracle (parse rejection or invalid-peer face)
    if 200 <= status < 300:
        return (f"DEFECT_FOUND (Type1_IllegalSuccess) — probe '{label}': expected 4xx, "
                f"got 2xx {status}; type-confused query value coerced and the removal "
                f"declared successful; body: {str(raw)[:200]}")
    return f"SCRIPT_ERROR — uninterpreted status {status} for probe '{label}'"


def main():
    tag = uuid.uuid4().hex[:8]
    print(f"ownership tag: bcpd4-{tag}")

    # Arrange: reachability probe + derived nonexistent peer id.
    disc = discover_cluster()
    if disc is None:
        print("VERDICT: SCRIPT_ERROR — discovery transport failure (no defect conclusion)")
        return
    cluster_status, known = disc
    if cluster_status == "DOWN":
        print("VERDICT: SCRIPT_ERROR — service down at discovery (no defect conclusion)")
        return
    ghost = derive_ghost_id(known)
    if ghost in known:
        print("VERDICT: SCRIPT_ERROR — ghost id derivation collided (no defect conclusion)")
        return
    print(f"derived nonexistent peer id for all probes: {ghost}")

    # Canonical controls first (clean parse expected; still 4xx here — no peer exists).
    controls = [
        ("control force=true (canonical)", {"force": "true"}),
        ("control force=false (canonical)", {"force": "false"}),
    ]
    probes = [
        ("force=TRUE (uppercase)", {"force": "TRUE"}),
        ("force=True (mixed case)", {"force": "True"}),
        ("force=yes", {"force": "yes"}),
        ("force=1 (numeric truthy)", {"force": "1"}),
        ("force=0 (numeric falsy)", {"force": "0"}),
        ("force=2 (numeric invalid)", {"force": "2"}),
        ("force='' (empty value)", {"force": ""}),
        ("force=null (literal)", {"force": "null"}),
        ("timeout=abc (non-numeric sibling param)", {"timeout": "abc"}),
        ("timeout=1.5 (float sibling param)", {"timeout": "1.5"}),
    ]
    verdict = None

    for label, params in controls:
        s, _, raw = safe_request("DELETE", f"/cluster/peer/{ghost}",
                                 params=params, timeout=30)
        print(f"[control {label}] -> status={s} raw={str(raw)[:200]}")
        v = judge_probe(label, s, raw)
        if v is not None and verdict is None:
            verdict = v

    for label, params in probes:
        s, _, raw = safe_request("DELETE", f"/cluster/peer/{ghost}",
                                 params=params, timeout=30)
        print(f"[probe {label}] -> status={s} raw={str(raw)[:250]}")
        # Strategy-5 soft diagnostics annotation (evidence only, no claim).
        low = str(raw).lower()
        if "force" in low or "timeout" in low:
            print("  NOTE(diagnostics): rejection body names the offending parameter")
        elif "distributed" in low or "disabled" in low:
            print("  NOTE(diagnostics): rejection body shows the distributed-mode gate "
                  "(query value passed deserialization)")
        v = judge_probe(label, s, raw)
        if v is not None and verdict is None:
            verdict = v

    if verdict is not None:
        print("VERDICT: " + verdict)
        return

    print("OK: all non-canonical force/timeout query spellings + canonical controls "
          "-> 4xx; no 2xx/5xx")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
