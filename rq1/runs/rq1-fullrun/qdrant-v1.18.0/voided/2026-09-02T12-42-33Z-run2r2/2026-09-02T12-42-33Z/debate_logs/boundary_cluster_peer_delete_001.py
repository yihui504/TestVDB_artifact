#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-boundary attack on the required PATH PARAMETER peer_id of
  cluster+peer+delete (DELETE /cluster/peer/{peer_id}) x
  qdrant_behavioral_cluster_peer_delete_001. peer_id is typed integer (u64) in the
  contract; the matrix attacks every NON-INTEGER FORM of the path segment:
    "abc" (alphabetic) | "-1" (negative) | "1.5" (float) | "1e3" (scientific)
    | "+7" (leading plus) | " 7" (leading whitespace) | "" (empty segment)
  plus one well-formed in-range control id (12345678) as the disposition contrast
  (same 4xx class expected on this standalone deployment because no peer exists).
  [chunk_cluster+peer+delete coverage: strategy2 type-confusion x
   qdrant_behavioral_cluster_peer_delete_001 — peer_id path-form face]
Oracle: every non-integer peer_id form returns 4xx (the assertion's documented
  "invalid peer id -> 4xx" face; a route/path-parse 404 also qualifies); any 2xx =
  Type1_IllegalSuccess (malformed peer id silently coerced and removal accepted);
  5xx = Type3_RuntimeFailure with /healthz rechecked before the verdict; transport
  failure with healthy /healthz = SCRIPT_ERROR; discovery transport failure = SCRIPT_ERROR.
Constraint: qdrant_behavioral_cluster_peer_delete_001
Blindspot: BS-01 Parameter Type Coercion Trust (path deserialization assumed to reject
  every non-integer spelling; -1 / 1.5 / 1e3 may slip through float-style coercion)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/remove-peer
doc_version: 1.18.x (versioned v-1-18-x api-reference)

Contract-driven route derivation (R4/R5 lesson: the chunk label is NOT a route):
  raw_knowledge.api_endpoints[]: path="cluster+peer+delete", method="DELETE",
  url="/cluster/peer/{peer_id}" -> used verbatim below. Parameter placement check
  (v34 R1 lesson): peer_id is in:path -> interpolated into the URL path, never
  stuffed into query/body. Deployment reachability probe FIRST (R5 lesson):
  GET /cluster (cluster+status) discovers the cluster mode and any real peer ids;
  real ids discovered at runtime (result.peer_id / result.peers) are EXCLUDED from
  probing (shared-deployment safety — never remove a real peer). On this standalone
  deployment ("disabled", no peers) every probe id is by construction an invalid
  peer id — exactly the face this assertion documents.
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
    """G8 liveness re-check: returns a Type3 verdict string if the service is down,
    else None (healthy service => transport anomaly is not a defect conclusion)."""
    hs, _, hraw = safe_request("GET", "/healthz", timeout=5)
    print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
    if hs <= 0 or hs >= 500:
        return (f"DEFECT_FOUND (Type3_RuntimeFailure) — probe '{label}' transport "
                f"failure and /healthz={hs} (service down)")
    return None


def discover_cluster():
    """GET /cluster (cluster+status) reachability probe (R5 lesson: probe before matrices).
    Returns (cluster_status, known_peer_ids) or None on transport failure."""
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


# Declare-first oracle (G7): the documented face for an invalid peer id is 4xx.
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
                f"(invalid peer id), got 2xx {status}; malformed peer id silently "
                f"accepted; body: {str(raw)[:200]}")
    return f"SCRIPT_ERROR — uninterpreted status {status} for probe '{label}'"


def main():
    tag = uuid.uuid4().hex[:8]
    print(f"ownership tag: bcpd1-{tag}")

    # Arrange: deployment reachability probe (R5 lesson) + real-peer exclusion guard.
    disc = discover_cluster()
    if disc is None:
        print("VERDICT: SCRIPT_ERROR — discovery transport failure (no defect conclusion)")
        return
    cluster_status, known = disc
    if cluster_status == "DOWN":
        print("VERDICT: SCRIPT_ERROR — service down at discovery (no defect conclusion)")
        return
    if cluster_status and cluster_status != "disabled":
        print(f"NOTE: cluster status={cluster_status!r} (distributed deployment) — "
              f"probe ids below are checked against the discovered peer set")

    # Act + Assert: non-integer path forms (peer_id is in:path -> URL interpolation).
    malformed = ["abc", "-1", "1.5", "1e3", "+7", " 7", ""]
    control = "12345678"  # well-formed in-range u64, never a discovered real peer id
    verdict = None

    for value in malformed:
        s, _, raw = safe_request("DELETE", f"/cluster/peer/{value}", timeout=30)
        print(f"[probe peer_id={value!r}] -> status={s} raw={str(raw)[:200]}")
        v = judge_probe(f"peer_id form {value!r}", s, raw)
        if v is not None and verdict is None:
            verdict = v

    # Disposition contrast control: well-formed id must land in the same 4xx class here
    # (no peer exists / invalid on this deployment per the assertion's 4xx face).
    if int(control) not in known:
        s, _, raw = safe_request("DELETE", f"/cluster/peer/{control}", timeout=30)
        print(f"[control peer_id={control!r} (well-formed)] -> status={s} raw={str(raw)[:200]}")
        v = judge_probe("control well-formed id", s, raw)
        if v is not None and verdict is None:
            verdict = v
    else:
        print(f"NOTE: control id {control} collides with a discovered real peer — skipped")

    if verdict is not None:
        print("VERDICT: " + verdict)
        return

    print("OK: all non-integer peer_id forms + well-formed control -> 4xx "
          "(documented invalid-peer-id face)")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
