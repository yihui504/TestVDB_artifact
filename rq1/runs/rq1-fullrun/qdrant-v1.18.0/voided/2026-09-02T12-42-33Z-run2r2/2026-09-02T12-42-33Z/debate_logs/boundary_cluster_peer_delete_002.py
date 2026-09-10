#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary-value attack on the required PATH PARAMETER peer_id of
  cluster+peer+delete (DELETE /cluster/peer/{peer_id}) x
  qdrant_behavioral_cluster_peer_delete_001. peer_id is typed integer (u64); the
  matrix hits the numeric range boundaries of that type:
    0 (smallest u64) | 1 | 18446744073709551615 (u64 max, boundary closure)
    | 18446744073709551616 (u64 max + 1 — overflow) | 36893488147419103232 (2^65).
  On this standalone deployment (cluster "disabled", no peers — R5-confirmed) every
  id is a NONEXISTENT peer, so the assertion's invalid-peer-id face applies to the
  in-range values too; the overflow values are additionally type-malformed.
  [chunk_cluster+peer+delete coverage: strategy1 boundary-matrix x
   qdrant_behavioral_cluster_peer_delete_001 — peer_id numeric-range face]
Oracle: every probe returns 4xx: in-range ids (0/1/u64 max) per the documented
  "invalid peer id -> 4xx" face, overflow ids (u64 max+1, 2^65) per u64 parse
  failure; any 2xx = Type1_IllegalSuccess — sharpest for an OVERFLOW value (silent
  truncation/wrapping of 18446744073709551616 into a valid peer id and a declared
  removal success); 5xx = Type3_RuntimeFailure with /healthz rechecked; transport
  failure with healthy /healthz = SCRIPT_ERROR; discovery failure = SCRIPT_ERROR.
Constraint: qdrant_behavioral_cluster_peer_delete_001
Blindspot: BS-04 Boundary Default Optimism (u64 upper bound assumed enforced by the
  path parser; overflow strings may be float-coerced to 1.8446744073709552e19)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/remove-peer
doc_version: 1.18.x (versioned v-1-18-x api-reference)

Contract-driven route derivation (R4/R5 lesson: the chunk label is NOT a route):
  raw_knowledge.api_endpoints[]: path="cluster+peer+delete", method="DELETE",
  url="/cluster/peer/{peer_id}" -> used verbatim. peer_id is in:path -> URL path
  interpolation only. Reachability probe FIRST (R5): GET /cluster discovers mode and
  real peer ids; discovered ids are dynamically EXCLUDED from the probe set (if 0 or
  1 happens to be the local peer id on some deployment, that probe is skipped with a
  NOTE — refusing to ever remove a real peer).
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

U64_MAX = 18446744073709551615


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


# Declare-first oracle (G7): invalid/nonexistent peer id -> 4xx.
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
        return None  # satisfies the documented "invalid peer id -> 4xx" face
    if 200 <= status < 300:
        return (f"DEFECT_FOUND (Type1_IllegalSuccess) — probe '{label}': expected 4xx "
                f"(invalid/nonexistent peer id), got 2xx {status}; body: {str(raw)[:200]}")
    return f"SCRIPT_ERROR — uninterpreted status {status} for probe '{label}'"


def main():
    tag = uuid.uuid4().hex[:8]
    print(f"ownership tag: bcpd2-{tag}")

    # Arrange: deployment reachability probe + real-peer exclusion guard.
    disc = discover_cluster()
    if disc is None:
        print("VERDICT: SCRIPT_ERROR — discovery transport failure (no defect conclusion)")
        return
    cluster_status, known = disc
    if cluster_status == "DOWN":
        print("VERDICT: SCRIPT_ERROR — service down at discovery (no defect conclusion)")
        return

    # Act + Assert: numeric boundary matrix on the path param.
    # in-range (well-formed u64, nonexistent on this deployment) + overflow (malformed).
    in_range = [0, 1, U64_MAX]
    overflow = [U64_MAX + 1, 36893488147419103232]  # 2^64, 2^65
    verdict = None

    for pid in in_range:
        if pid in known:
            print(f"NOTE: id {pid} collides with a discovered real peer — skipped")
            continue
        s, _, raw = safe_request("DELETE", f"/cluster/peer/{pid}", timeout=30)
        print(f"[probe in-range peer_id={pid}] -> status={s} raw={str(raw)[:200]}")
        v = judge_probe(f"in-range peer_id {pid}", s, raw)
        if v is not None and verdict is None:
            verdict = v

    for pid in overflow:
        s, _, raw = safe_request("DELETE", f"/cluster/peer/{pid}", timeout=30)
        print(f"[probe overflow peer_id={pid}] -> status={s} raw={str(raw)[:200]}")
        v = judge_probe(f"overflow peer_id {pid}", s, raw)
        if v is not None and verdict is None:
            verdict = v

    if verdict is not None:
        print("VERDICT: " + verdict)
        return

    print("OK: in-range and overflow peer_id boundary values -> 4xx "
          "(documented invalid-peer-id face; overflow rejected at parse)")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
