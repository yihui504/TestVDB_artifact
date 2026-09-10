#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary-value on the PEER-ID numeric family of
  cluster+collection+update (POST /collections/{collection_name}/cluster) x
  qdrant_behavioral_cluster_collection_update_001 (400 face: "invalid peer/shard returns 400").
  peer_id is a uint64 (per the cluster+status response constraint: "peer_id (uint64)"), so the
  boundary matrix walks the u64 closure from both ends plus the overflow edge:
    -1 (negative, out of unsigned domain) | 0 (legal u64, guaranteed non-existent peer) |
    real_peer+1_000_000 (legal u64, derived-guaranteed non-existent) |
    18446744073709551615 (u64 MAX — legal value, non-existent peer) |
    18446744073709551616 (u64 MAX+1 — outside the type domain, serde must range-reject).
  Isolation: probes ride the drop_replica variant {shard_id: <real existing shard>,
  peer_id: <probe>} so the ONLY varied factor is the peer id; one extra move_shard probe
  (from_peer_id=real, to_peer_id=bogus) exercises the constraint's own example operation on
  the invalid-peer face. No real peer id is ever hardcoded: it is discovered at runtime from
  GET /cluster (envelope result.peer_id) and GET /collections/{name}/cluster.
  [chunk_cluster+collection+update coverage: strategy1 boundary-value(peer_id) x
   qdrant_behavioral_cluster_collection_update_001 — 400 face]
Oracle: every invalid-peer probe returns 400 or 422 (invalid peer / validation error);
  2xx = Type1_IllegalSuccess (a transfer/replica operation accepted against an invalid peer);
  4xx other than 400/422 = Type2_PoorDiagnostics (misdirected face); 5xx =
  Type3_RuntimeFailure with /healthz rechecked; transport failure with healthy /healthz =
  SCRIPT_ERROR; discovery failure of the real peer = SCRIPT_ERROR (no fallback hardcode).
Constraint: qdrant_behavioral_cluster_collection_update_001
Blindspot: BS-01 Parameter Type Coercion Trust (u64 numeric edges trusted to serde) +
  BS-04 Boundary Default Optimism (invalid peer assumed rejected)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/update-collection-cluster
doc_version: 1.18.x (versioned v-1-18-x api-reference)

Contract-driven route derivation (R4 lesson: the chunk label is NOT a route):
  raw_knowledge.api_endpoints[]: path="cluster+collection+update", method="POST",
  url="/collections/{collection_name}/cluster"; peer-discovery instrument = cluster+status
  GET /cluster (url field of raw_knowledge); shard-discovery instrument = cluster+collection+info
  GET /collections/{collection_name}/cluster (url field of raw_knowledge).
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


def safe_request(method, endpoint, json=None, params=None, data=None, timeout=10):
    """
    Safe HTTP request wrapper with unified error handling (agents/_target_api_reference.md).
    Returns: (status_code, body, raw_text)
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
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


def drop_collection(name):
    try:
        safe_request("DELETE", f"/collections/{name}", params={"timeout": 60}, timeout=60)
    except Exception:
        pass  # cleanup failures are non-fatal


# Declare-first oracle: documented 400 face for an invalid peer = 400/422 rejection.
EXPECT_STATUS = (400, 422)
U64_MAX = 18446744073709551615
U64_MAX_PLUS_1 = 18446744073709551616


def judge_probe(label, status, raw):
    """Declare-first adjudication ladder for one probe. Returns verdict string or None."""
    if status <= 0:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=5)
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        if hs <= 0 or hs >= 500:
            return (f"DEFECT_FOUND (Type3_RuntimeFailure) — probe '{label}' transport "
                    f"failure and /healthz={hs} (service down)")
        return "SCRIPT_ERROR — transport failure with healthy /healthz (no defect conclusion)"
    if 500 <= status <= 599:
        hs, _, hraw = safe_request("GET", "/healthz", timeout=5)
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        if hs <= 0 or hs >= 500:
            return (f"DEFECT_FOUND (Type3_RuntimeFailure) — probe '{label}' got {status} "
                    f"and /healthz={hs} (service down)")
        return (f"DEFECT_FOUND (Type3_RuntimeFailure) — probe '{label}' got {status} "
                f"with /healthz={hs} alive")
    if status in EXPECT_STATUS:
        # Type-2 observational note only (message quality, not verdict-driving):
        low = str(raw).lower()
        if "peer" not in low:
            print(f"NOTE(judge, Type2_PoorDiagnostics signal): rejection of '{label}' does "
                  f"not name the peer parameter; body: {str(raw)[:200]}")
        return None  # matches the documented 400 face
    if 200 <= status < 300:
        return (f"DEFECT_FOUND (Type1_IllegalSuccess) — probe '{label}': expected 400/422 "
                f"(invalid peer), got 2xx {status}; an operation was ACCEPTED against an "
                f"invalid peer; body: {str(raw)[:200]}")
    if 400 <= status < 500:
        return (f"DEFECT_FOUND (Type2_PoorDiagnostics) — probe '{label}': expected 400/422, "
                f"got {status} (rejected on the wrong documented face); body: {str(raw)[:200]}")
    return f"SCRIPT_ERROR — uninterpreted status {status} for probe '{label}'"


def discover_context(coll):
    """Discover (peer_id, existing_shard_id) at runtime; None on failure (no hardcode)."""
    s, _, raw = safe_request("GET", "/cluster", timeout=15)
    print(f"[discover GET /cluster] status={s} raw={str(raw)[:200]}")
    peer_id = None
    try:
        node = json.loads(raw).get("result")
        if isinstance(node, dict) and isinstance(node.get("peer_id"), int):
            peer_id = node["peer_id"]
    except Exception:
        peer_id = None
    if peer_id is None:
        return None
    s, _, raw = safe_request("GET", f"/collections/{coll}/cluster", timeout=15)
    print(f"[discover collection cluster info] status={s} raw={str(raw)[:200]}")
    shard_id = None
    try:
        node = json.loads(raw).get("result")
        if isinstance(node, dict):
            local = node.get("local_shards") or []
            for entry in local:
                if isinstance(entry, dict) and isinstance(entry.get("shard_id"), int):
                    shard_id = entry["shard_id"]
                    break
    except Exception:
        shard_id = None
    if shard_id is None:
        return None
    return peer_id, shard_id


def main():
    tag = uuid.uuid4().hex[:8]
    pfx = "bccu2" + tag
    coll = pfx + "c"
    print(f"ownership prefix: {pfx}")

    # Arrange: create one collection (contract-required body: vectors VectorParams)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create {coll} failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return

    try:
        ctx = discover_context(coll)
        if ctx is None:
            print("VERDICT: SCRIPT_ERROR — runtime discovery of peer_id/shard_id failed "
                  "(refusing to hardcode; no defect conclusion)")
            return
        peer_id, shard_id = ctx
        print(f"discovered: peer_id={peer_id} shard_id={shard_id}")
        bogus_peer = peer_id + 1000000

        # Act + Assert: peer-id boundary matrix, only the peer id varies.
        probes = [
            ("drop_replica.peer_id=-1 (out of unsigned domain)",
             {"drop_replica": {"shard_id": shard_id, "peer_id": -1}}),
            ("drop_replica.peer_id=0 (legal u64, non-existent peer)",
             {"drop_replica": {"shard_id": shard_id, "peer_id": 0}}),
            (f"drop_replica.peer_id={bogus_peer} (derived-guaranteed non-existent)",
             {"drop_replica": {"shard_id": shard_id, "peer_id": bogus_peer}}),
            ("drop_replica.peer_id=u64max (18446744073709551615, legal value)",
             {"drop_replica": {"shard_id": shard_id, "peer_id": U64_MAX}}),
            ("drop_replica.peer_id=u64max+1 (18446744073709551616, type-domain overflow)",
             {"drop_replica": {"shard_id": shard_id, "peer_id": U64_MAX_PLUS_1}}),
            (f"move_shard.to_peer_id={bogus_peer} (constraint's example op, invalid peer)",
             {"move_shard": {"shard_id": shard_id,
                             "from_peer_id": peer_id, "to_peer_id": bogus_peer}}),
        ]
        verdict = None
        for label, body in probes:
            s, _, raw = safe_request("POST", f"/collections/{coll}/cluster",
                                     json=body, timeout=30)
            print(f"[probe {label}] -> status={s} raw={str(raw)[:200]}")
            v = judge_probe(label, s, raw)
            if v is not None and verdict is None:
                verdict = v

        if verdict is not None:
            print("VERDICT: " + verdict)
            return

        print("OK: 6/6 invalid-peer probes -> 400/422 (documented invalid-peer face)")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            drop_collection(coll)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
