#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-boundary / type-confusion on the required `operation` REQUEST BODY of
  cluster+collection+update (POST /collections/{collection_name}/cluster) x
  qdrant_behavioral_cluster_collection_update_001. The contract parameter `operation` is a
  oneOf (variant enum: move_shard|replicate_shard|abort_transfer|drop_replica|
  create_sharding_key|drop_sharding_key|restart_transfer|start_resharding|
  abort_resharding|replicate_states) carried as the single top-level body key. The type
  matrix attacks every layer of that structure on an EXISTING collection with discovered
  real peer/shard values so that only the shape defect varies:
    {} (missing operation — required param absent) |
    {"move_shard": null} (variant value nulled) |
    {"move_shard": {}} (variant present, required inner fields missing) |
    {"move_shard": "move_it"} (object -> string) |
    {"move_shard": []} (object -> array) |
    {"nonexistent_operation": {}} (unknown variant key) |
    {"move_shard": {shard_id/to_peer_id/from_peer_id as STRINGS}} (int fields -> string) |
    {"move_shard": {...}, "replicate_shard": {...}} (two variants — oneOf violation) |
    ["move_shard"] (whole body as array instead of object).
  [chunk_cluster+collection+update coverage: strategy2 type-confusion x
   qdrant_behavioral_cluster_collection_update_001 — 400 face, request-body side]
Oracle: every type-confused body returns 400 or 422 (validation error); 2xx =
  Type1_IllegalSuccess (malformed oneOf body silently accepted — serde coercion trusted);
  4xx other than 400/422 = Type2_PoorDiagnostics (misdirected face); 5xx =
  Type3_RuntimeFailure with /healthz rechecked; transport failure with healthy /healthz =
  SCRIPT_ERROR; discovery failure = SCRIPT_ERROR (no fallback hardcode).
Constraint: qdrant_behavioral_cluster_collection_update_001
Blindspot: BS-01 Parameter Type Coercion Trust (REST framework assumed to validate the
  nested oneOf structure; null/object/array/string mismatches may pass silently)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/update-collection-cluster
doc_version: 1.18.x (versioned v-1-18-x api-reference)

Contract-driven route derivation (R4 lesson: the chunk label is NOT a route):
  raw_knowledge.api_endpoints[]: path="cluster+collection+update", method="POST",
  url="/collections/{collection_name}/cluster"; discovery instruments = cluster+status
  GET /cluster and cluster+collection+info GET /collections/{collection_name}/cluster.
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


# Declare-first oracle: type-confused oneOf body = 400/422 validation rejection.
EXPECT_STATUS = (400, 422)


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
        return None  # matches the documented validation-error face
    if 200 <= status < 300:
        return (f"DEFECT_FOUND (Type1_IllegalSuccess) — probe '{label}': expected 400/422 "
                f"(type-confused operation body), got 2xx {status}; malformed oneOf body "
                f"silently accepted; body: {str(raw)[:200]}")
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
    pfx = "bccu4" + tag
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

        valid_move = {"shard_id": shard_id,
                      "from_peer_id": peer_id, "to_peer_id": peer_id}

        # Act + Assert: type-confusion matrix on the oneOf operation body.
        probes = [
            ("empty body {} (operation param missing)", {}),
            ("variant value null {move_shard: null}", {"move_shard": None}),
            ("variant value empty object {move_shard: {}}", {"move_shard": {}}),
            ("variant value string {move_shard: 'move_it'}", {"move_shard": "move_it"}),
            ("variant value array {move_shard: []}", {"move_shard": []}),
            ("unknown variant key {nonexistent_operation: {}}",
             {"nonexistent_operation": {}}),
            ("int fields as strings {move_shard: {shard_id: '0', ...}}",
             {"move_shard": {"shard_id": str(shard_id),
                             "from_peer_id": str(peer_id), "to_peer_id": str(peer_id)}}),
            ("two variants at once (oneOf violation)",
             {"move_shard": dict(valid_move),
              "replicate_shard": dict(valid_move)}),
            ("whole body as array ['move_shard']", ["move_shard"]),
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

        print("OK: 9/9 type-confused operation bodies -> 400/422 (validation face)")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            drop_collection(coll)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
