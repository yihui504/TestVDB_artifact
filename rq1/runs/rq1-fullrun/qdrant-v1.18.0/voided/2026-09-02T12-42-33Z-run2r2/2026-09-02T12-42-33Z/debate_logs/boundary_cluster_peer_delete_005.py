#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: system-level state-constraint both-direction attack (D2 general scenario,
  G4 positive-negative pairing) on cluster+peer+delete (DELETE /cluster/peer/{peer_id})
  x qdrant_state_cluster_peer_delete_001 — "peer removal is destructive by design:
  force=true bypasses safety checks, removal of a peer holding the only replica can
  lose data; a 200 does not guarantee consensus survival". Exercisable faces on THIS
  deployment, probed against a runtime-derived nonexistent peer id:
    positive = a spec-legal well-formed removal request is issued and the safety
      layer's observable promise holds (unknown peer refused with clean 4xx, node
      stays alive and cluster state is unchanged);
    negative = the destructive face with force=true / force=false / absent must NOT
      manufacture a false success (200 = Type1: success declared for a peer that
      does not exist — the constraint itself warns such a 200 guarantees nothing)
      and must NOT destabilize the single node (healthz down = Type3; cluster-state
      drift after failed removals = Type4_StateLogicViolation).
  DEPLOYMENT-BOUNDARY DECLARATION (R5 lesson, stated up front): this deployment is
  standalone (GET /cluster expected to report result.status="disabled" with no
  peers); the multi-peer faces of this system-level constraint — last-peer/self
  removal breaking raft consensus, only-replica data loss, and the assertion's
  200 "valid removal" face — are NOT exercisable here and are recorded as
  deployment-boundary unreachables, NOT as defects and NOT as SKIPPED-by-design.
  [chunk_cluster+peer+delete coverage: state-constraint both-direction (general
   scenario) x qdrant_state_cluster_peer_delete_001 — force/id face + stability]
Oracle: all three removal attempts (force=true, force=false, force absent) against
  the derived nonexistent id return 4xx (never 200 — a 200 = Type1_IllegalSuccess,
  false success on a nonexistent peer); after the attempts GET /healthz = 200 and
  GET /cluster result.status equals the pre-probe baseline status (drift =
  Type4_StateLogicViolation; healthz down = Type3_RuntimeFailure); 5xx on any
  removal attempt = Type3 with /healthz rechecked; transport failure with healthy
  /healthz = SCRIPT_ERROR; discovery failure = SCRIPT_ERROR (no hardcoded peer id).
Constraint: qdrant_state_cluster_peer_delete_001
Blindspot: BS-03 Concurrency/Cluster State Blindness (destructive cluster ops
  assumed safe on single-node; removal attempts may still corrupt state or liveness)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/remove-peer
doc_version: 1.18.x (versioned v-1-18-x api-reference)

Contract-driven route derivation (R4/R5 lesson: the chunk label is NOT a route):
  raw_knowledge.api_endpoints[]: path="cluster+peer+delete", method="DELETE",
  url="/cluster/peer/{peer_id}", parameters: force (boolean, query, default false).
  force is in:QUERY -> params=. Discovery instruments: cluster+status GET /cluster
  (url verbatim) and healthz GET /healthz. The probe id is DERIVED at runtime
  (max(discovered)+1, else uuid-derived) — a real discovered peer is NEVER removed.
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


def read_cluster():
    """GET /cluster -> (status_code, result_status_text, known_peer_ids)."""
    s, _, raw = safe_request("GET", "/cluster", timeout=15)
    known = set()
    status_text = ""
    if s > 0:
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
    return s, status_text, known


def derive_ghost_id(known):
    """Derive a guaranteed-nonexistent peer id at runtime (no hardcode; R5 lesson)."""
    if known:
        return max(known) + 1
    return (uuid.uuid4().int >> 2) & 0x7FFFFFFFFFFFFFFF


def main():
    tag = uuid.uuid4().hex[:8]
    print(f"ownership tag: bcpd5-{tag}")

    # Arrange: reachability probe, baseline snapshot, derived nonexistent id.
    s0, cluster_status, known = read_cluster()
    print(f"[discover GET /cluster] status={s0} cluster_status={cluster_status!r} "
          f"known_peer_ids={sorted(known)}")
    if s0 <= 0:
        if healthz_ladder("GET /cluster discovery") is not None:
            print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — discovery shows service down")
            return
        print("VERDICT: SCRIPT_ERROR — discovery transport failure (no defect conclusion)")
        return
    hs0, _, hraw0 = safe_request("GET", "/healthz", timeout=5)
    print(f"[baseline /healthz] status={hs0} raw={str(hraw0)[:120]}")
    if hs0 != 200:
        print(f"VERDICT: SCRIPT_ERROR — baseline /healthz={hs0} (unhealthy start, no conclusion)")
        return
    if cluster_status == "disabled":
        print("NOTE(deployment boundary): standalone deployment (cluster 'disabled', "
              "no peers) — the constraint's multi-peer consensus/data-loss faces and "
              "the behavioral 200 'valid removal' face are NOT exercisable here; "
              "recorded as unreachable, no defect claim")

    ghost = derive_ghost_id(known)
    if ghost in known:
        print("VERDICT: SCRIPT_ERROR — ghost id derivation collided (no defect conclusion)")
        return
    print(f"derived nonexistent peer id: {ghost}")

    # Act: destructive-face attempts — force=true / force=false / absent.
    attempts = [
        ("force=true (destructive bypass flag)", {"force": "true"}),
        ("force=false (explicit safe default)", {"force": "false"}),
        ("force absent (documented default)", None),
    ]
    verdict = None
    for label, params in attempts:
        s, _, raw = safe_request("DELETE", f"/cluster/peer/{ghost}",
                                 params=params, timeout=30)
        print(f"[attempt {label}] -> status={s} raw={str(raw)[:250]}")
        if s <= 0:
            v = healthz_ladder(label)
            if v is not None and verdict is None:
                verdict = v
            elif v is None and verdict is None:
                verdict = "SCRIPT_ERROR — transport failure with healthy /healthz (no defect conclusion)"
        elif 500 <= s <= 599:
            v = healthz_ladder(label)
            if v is not None and verdict is None:
                verdict = v
            elif v is None and verdict is None:
                verdict = (f"DEFECT_FOUND (Type3_RuntimeFailure) — attempt '{label}' got "
                           f"{s} with /healthz alive; body: {str(raw)[:200]}")
        elif 200 <= s < 300:
            if verdict is None:
                verdict = (f"DEFECT_FOUND (Type1_IllegalSuccess) — attempt '{label}': 2xx "
                           f"{s} returned for a peer id that does not exist (false "
                           f"success; the constraint warns a 200 guarantees nothing); "
                           f"body: {str(raw)[:200]}")
        elif not (400 <= s < 500) and verdict is None:
            verdict = f"SCRIPT_ERROR — uninterpreted status {s} for attempt '{label}'"
        # 4xx = the observable safety promise holds (unknown peer refused cleanly)

    # Assert: node stability + cluster-state non-corruption after failed removals.
    hs1, _, hraw1 = safe_request("GET", "/healthz", timeout=5)
    s1, cluster_status_after, _ = read_cluster()
    print(f"[post /healthz] status={hs1} raw={str(hraw1)[:120]}")
    print(f"[post GET /cluster] status={s1} cluster_status={cluster_status_after!r}")
    if verdict is None:
        if hs1 != 200:
            print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — /healthz degraded "
                  f"from 200 to {hs1} after removal attempts on a nonexistent peer")
            return
        if cluster_status_after != cluster_status:
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — cluster status "
                  f"drifted {cluster_status!r} -> {cluster_status_after!r} after failed "
                  f"removal attempts")
            return
        print("OK: destructive-face attempts (force=true/false/absent) all refused 4xx "
              "on the nonexistent peer; /healthz 200; cluster status unchanged")
        print("VERDICT: NO_DEFECT")
    else:
        print("VERDICT: " + verdict)


if __name__ == "__main__":
    main()
