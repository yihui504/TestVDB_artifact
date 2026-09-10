#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary-value on the SHARD-ID numeric family of
  cluster+collection+update (POST /collections/{collection_name}/cluster) x
  qdrant_behavioral_cluster_collection_update_001 (400 face: "invalid peer/shard returns 400").
  shard ids are 32-bit unsigned in the cluster-operation bodies, so the matrix walks the u32
  closure and the existence edge:
    -1 (negative, out of unsigned domain) |
    4294967295 (u32 MAX — legal value, non-existent shard) |
    4294967296 (u32 MAX+1 — type-domain overflow, serde must range-reject) |
    8888 (legal u32 inside domain, guaranteed non-existent shard of this collection).
  Isolation: probes ride drop_replica {shard_id: <probe>, peer_id: <real peer>} so the ONLY
  varied factor is the shard id; one extra abort_transfer probe (all-real peers, bogus shard)
  exercises the transfer-family variant on the invalid-shard face. The real peer and the
  existing shard are discovered at runtime (GET /cluster, GET /collections/{name}/cluster) —
  nothing DB-specific is hardcoded.
  [chunk_cluster+collection+update coverage: strategy1 boundary-value(shard_id) x
   qdrant_behavioral_cluster_collection_update_001 — 400 face]
Oracle: every invalid-shard probe returns 400 or 422 (invalid shard / validation error);
  2xx = Type1_IllegalSuccess (a replica/transfer operation accepted against an invalid
  shard); 4xx other than 400/422 = Type2_PoorDiagnostics (misdirected face); 5xx =
  Type3_RuntimeFailure with /healthz rechecked; transport failure with healthy /healthz =
  SCRIPT_ERROR; discovery failure = SCRIPT_ERROR (no fallback hardcode).
Constraint: qdrant_behavioral_cluster_collection_update_001
Blindspot: BS-01 Parameter Type Coercion Trust (u32 numeric edges trusted to serde) +
  BS-04 Boundary Default Optimism (invalid shard assumed rejected)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/update-collection-cluster
doc_version: 1.18.x (versioned v-1-18-x api-reference)

Contract-driven route derivation (R4 lesson: the chunk label is NOT a route):
  raw_knowledge.api_endpoints[]: path="cluster+collection+update", method="POST",
  url="/collections/{collection_name}/cluster"; discovery instruments = cluster+status
  GET /cluster and cluster+collection+info GET /collections/{collection_name}/cluster
  (url fields of raw_knowledge).
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


# Declare-first oracle: documented 400 face for an invalid shard = 400/422 rejection.
EXPECT_STATUS = (400, 422)
U32_MAX = 4294967295
U32_MAX_PLUS_1 = 4294967296
BOGUS_IN_DOMAIN = 8888


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
        if "shard" not in low:
            print(f"NOTE(judge, Type2_PoorDiagnostics signal): rejection of '{label}' does "
                  f"not name the shard parameter; body: {str(raw)[:200]}")
        return None  # matches the documented 400 face
    if 200 <= status < 300:
        return (f"DEFECT_FOUND (Type1_IllegalSuccess) — probe '{label}': expected 400/422 "
                f"(invalid shard), got 2xx {status}; an operation was ACCEPTED against an "
                f"invalid shard; body: {str(raw)[:200]}")
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
    pfx = "bccu3" + tag
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
        print(f"discovered: peer_id={peer_id} existing shard_id={shard_id}")

        # Act + Assert: shard-id boundary matrix, only the shard id varies.
        probes = [
            ("drop_replica.shard_id=-1 (out of unsigned domain)",
             {"drop_replica": {"shard_id": -1, "peer_id": peer_id}}),
            ("drop_replica.shard_id=4294967295 (u32max, legal value, non-existent)",
             {"drop_replica": {"shard_id": U32_MAX, "peer_id": peer_id}}),
            ("drop_replica.shard_id=4294967296 (u32max+1, type-domain overflow)",
             {"drop_replica": {"shard_id": U32_MAX_PLUS_1, "peer_id": peer_id}}),
            (f"drop_replica.shard_id={BOGUS_IN_DOMAIN} (in-domain, non-existent shard)",
             {"drop_replica": {"shard_id": BOGUS_IN_DOMAIN, "peer_id": peer_id}}),
            (f"abort_transfer.shard_id={BOGUS_IN_DOMAIN} (transfer family, real peers)",
             {"abort_transfer": {"shard_id": BOGUS_IN_DOMAIN,
                                 "to_peer_id": peer_id, "from_peer_id": peer_id}}),
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

        print("OK: 5/5 invalid-shard probes -> 400/422 (documented invalid-shard face)")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            drop_collection(coll)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
