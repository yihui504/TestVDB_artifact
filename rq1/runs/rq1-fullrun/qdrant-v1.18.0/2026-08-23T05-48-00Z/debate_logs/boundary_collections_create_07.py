#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: resource_limit (strategy 6) — extreme numeric config values on create
Constraint: qdrant_type_collections_create_002 (vectors.size uint64) + range 001-003 extreme side
Endpoint: PUT /collections/{collection_name} (contract path: collections+create)
exploration_target: novel_candidate
Block: chunk_collections+create-1of2
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
doc_version: 1.18.x (versioned)
# Blindspot: BS-04, BS-07
"""

import requests
import json
import sys
import os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)
AUTH_HEADER = os.environ.get("TESTVDB_AUTH_HEADER", "")


def safe_request(method, path, **kwargs):
    url = f"{BASE_URL}{path}"
    headers = kwargs.pop("headers", {"Content-Type": "application/json"})
    if AUTH_HEADER:
        headers["Authorization"] = AUTH_HEADER
    try:
        resp = requests.request(method, url, headers=headers, timeout=60, **kwargs)
        status = resp.status_code
        text = resp.text
        try:
            body = resp.json() if text else {}
        except (json.JSONDecodeError, ValueError):
            return status, None, text
        return status, body, text
    except requests.exceptions.RequestException as e:
        print(f"REQUEST_ERROR: {e}")
        return 0, None, ""


BASE = {"vectors": {"size": 4, "distance": "Cosine"}}
INT_MAX = 2147483647
CRASH_KEYS = ["oom", "out of memory", "panic", "capacity overflow", "killed", "backtrace"]


def judge(name, status, raw):
    if status == 0:
        print("VERDICT: SCRIPT_ERROR — connection failed (possible container crash)")
        return True
    print(f"CASE {name}: status={status} body={raw[:300]}")
    if status in (500, 502, 503, 504) or any(k in raw.lower() for k in CRASH_KEYS):
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — {name} triggered 5xx/crash")
        return True
    if status in (200, 201):
        print(f"VERDICT: NO_DEFECT — {name} accepted (resource upper bound not required, no crash)")
        try:
            safe_request("DELETE", "/collections/" + name.replace("CASE ", ""))
        except Exception:
            pass
    elif status in (400, 422):
        print(f"VERDICT: NO_DEFECT — {name} correctly rejected")
    return False


def test_resource_limits():
    # NOTE: vectors.size extreme values are 'dimension' class per strategy 6
    cases = [
        ("bnd_crt_rl_1", {"vectors": {"size": 65536, "distance": "Cosine"}}),
        ("bnd_crt_rl_2", {"vectors": {"size": 100000, "distance": "Cosine"}}),
        ("bnd_crt_rl_3", {"vectors": {"size": 1000000, "distance": "Cosine"}}),
        ("bnd_crt_rl_4", {"vectors": {"size": INT_MAX, "distance": "Cosine"}}),
        # uint64 max edge (json int, above INT64 -> serde should reject, not panic)
        ("bnd_crt_rl_5", {"vectors": {"size": 18446744073709551615, "distance": "Cosine"}}),
        # extreme hnsw_config
        ("bnd_crt_rl_6", {**BASE, "hnsw_config": {"m": INT_MAX}}),
        ("bnd_crt_rl_7", {**BASE, "hnsw_config": {"ef_construct": INT_MAX}}),
        ("bnd_crt_rl_8", {**BASE, "hnsw_config": {"max_indexing_threads": INT_MAX}}),
        ("bnd_crt_rl_9", {**BASE, "optimizers_config": {"max_optimization_threads": INT_MAX}}),
        ("bnd_crt_rl_10", {**BASE, "optimizers_config": {"indexing_threshold": INT_MAX, "memmap_threshold": INT_MAX}}),
        ("bnd_crt_rl_11", {**BASE, "wal_config": {"wal_capacity_mb": INT_MAX}}),
        ("bnd_crt_rl_12", {**BASE, "shard_number": INT_MAX, "replication_factor": INT_MAX, "write_consistency_factor": INT_MAX}),
    ]
    defect = False
    for cname, payload in cases:
        status, body, raw = safe_request("PUT", f"/collections/{cname}", json=payload)
        if judge(cname, status, raw):
            if status == 0:
                return
            if status >= 500:
                defect = True
        else:
            try:
                safe_request("DELETE", f"/collections/{cname}")
            except Exception:
                pass
    if not defect:
        print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        test_resource_limits()
    finally:
        pass
