#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy2 type-boundary on the RESPONSE SHAPE of cluster+collection+info (GET /cluster/collection/{collection_name}) — positive promise-exercise: a 200 on an existing collection must return the documented CollectionClusterInfo with all six fields present and correctly typed; boundary clause shard_count (minimum 0) must never be negative. Probes: field-presence x6, peer_id:int, shard_count:int AND >=0, local_shards/remote_shards/shard_transfers/resharding_operations:list, plus an observational (non-verdict) shard_count vs sum(local+remote) consistency print.
Oracle: existing collection -> GET cluster info returns HTTP 200 whose envelope nests result as an object containing peer_id (integer), shard_count (integer >= 0, never negative), local_shards, remote_shards, shard_transfers, resharding_operations (each an array); 200 with any of the six fields missing, shard_count non-integer or negative, or any array-field non-array = Type4_StateLogicViolation against constraint qdrant_type_cluster_collection_info_001; 5xx = Type3_RuntimeFailure (healthz rechecked before verdict); transport failure with healthy healthz = SCRIPT_ERROR.
Constraint: qdrant_type_cluster_collection_info_001
Blindspot: BS-01 Parameter Type Coercion Trust (response side — serde may serialize a variant that drops/renames documented fields and the framework is trusted to match the documented shape)
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/collection-cluster-info
doc_version: 1.18.x (versioned v-1-18-x api-reference)

Contract-driven path derivation (no hardcoding from memory):
  contract.api_endpoints[]: path="cluster+collection+info", method="GET",
  category=admin, parameters=[{name: collection_name, type: string,
  required: true, description: "path"}]
  -> `+`-slug translated to `/`-separated REST route with the documented
     path parameter as terminal segment: /cluster/collection/{collection_name}
Setup face (collections+create) also from contract: PUT /collections/{name}
with required body field vectors = VectorParams{size, distance}.
R3 lessons applied: envelope nests at result.<field>; unique per-script
ownership prefix; no list.remove() bookkeeping.
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
    Safe HTTP request wrapper with unified error handling.
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


def liveness():
    hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
    return hs, hraw


def drop_collection(name):
    try:
        safe_request("DELETE", f"/collections/{name}", params={"timeout": 60}, timeout=60)
    except Exception:
        pass  # cleanup failures are non-fatal


def main():
    tag = uuid.uuid4().hex[:8]
    pfx = "bcci1" + tag
    coll = pfx + "c1"
    print(f"ownership prefix: {pfx}")

    # Arrange: create one collection (contract-required body: vectors VectorParams)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create {coll} failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return

    try:
        # Act: GET the per-collection cluster info face
        s, b, raw = safe_request("GET", f"/cluster/collection/{coll}", timeout=30)
        print(f"GET cluster info -> status={s}")
        print(f"raw: {raw[:600]}")
        if s <= 0:
            hs, hraw = liveness()
            print(f"transport failure (healthz status={hs}: {str(hraw)[:200]})")
            if hs <= 0 or hs >= 500:
                print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — GET cluster info "
                      "on an existing collection killed the service (healthz="
                      f"{hs})")
            else:
                print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
            return
        if 500 <= s <= 599:
            hs, hraw = liveness()
            if hs <= 0 or hs >= 500:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {s} on cluster "
                      f"info for an existing collection and healthz={hs} (service down)")
            else:
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {s} on cluster "
                      f"info for an existing collection (healthz={hs} alive)")
            return
        if s != 200:
            # behavioral assertion promises 200 for an existing collection;
            # that face is adjudicated in script 002/004 — here it invalidates setup
            print(f"VERDICT: SCRIPT_ERROR — expected 200 for existing collection, "
                  f"got {s}; shape check not reachable")
            return

        # Assert: envelope result.<field> holds CollectionClusterInfo
        try:
            parsed = json.loads(raw)
        except Exception:
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — 200 but body "
                  "is not JSON; CollectionClusterInfo shape violated")
            return
        if not isinstance(parsed, dict) or not isinstance(parsed.get("result"), dict):
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — 200 but "
                  "envelope does not nest CollectionClusterInfo at result "
                  f"(got: {raw[:200]})")
            return
        info = parsed["result"]

        required = {
            "peer_id": "int",
            "shard_count": "int",
            "local_shards": "list",
            "remote_shards": "list",
            "shard_transfers": "list",
            "resharding_operations": "list",
        }
        for field, kind in required.items():
            if field not in info:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — 200 but "
                      f"documented field '{field}' missing from CollectionClusterInfo "
                      f"(constraint qdrant_type_cluster_collection_info_001); "
                      f"fields present: {sorted(info.keys())}")
                return
            v = info[field]
            if kind == "int" and not (isinstance(v, int) and not isinstance(v, bool)):
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — field "
                      f"'{field}' must be integer, got {type(v).__name__}={v!r}")
                return
            if kind == "list" and not isinstance(v, list):
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — field "
                      f"'{field}' must be an array, got {type(v).__name__}={v!r}")
                return

        # Boundary clause of the constraint: shard_count minimum 0 — value must
        # never be negative (0 itself is the legal closure).
        if info["shard_count"] < 0:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — shard_count="
                  f"{info['shard_count']} violates documented minimum 0")
            return

        # Observational only (semantic, not explicit in the constraint text):
        # shard_count vs local+remote shard entries — recorded for the judge.
        total_entries = len(info["local_shards"]) + len(info["remote_shards"])
        if info["shard_count"] != total_entries:
            print(f"NOTE(judge): shard_count={info['shard_count']} != "
                  f"len(local_shards)+len(remote_shards)={total_entries} "
                  f"(semantic observation, not contract-explicit)")
        else:
            print(f"OK: shard_count={info['shard_count']} consistent with "
                  f"{total_entries} shard entries")

        print("OK: 200 with full CollectionClusterInfo shape (6/6 fields, "
              "peer_id:int, shard_count:int>=0, four array fields)")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            drop_collection(coll)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
