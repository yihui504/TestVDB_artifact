#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: boundary_value (strategy 1) — hnsw_config range constraints
Constraint: qdrant_range_collections_create_001 (m>=0) + 002 (ef_construct>=4) + 003 (full_scan_threshold>=0)
Endpoint: PUT /collections/{collection_name} (contract path: collections+create)
exploration_target: novel_candidate
Block: chunk_collections+create-1of2
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
doc_version: 1.18.x (versioned)
# Blindspot: BS-04 Boundary Default Optimism
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
        resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
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


def test_hnsw_ranges():
    cases = [
        # constraint 001: m >= 0 -> m=-1 must be rejected; m=0 spec-min allowed (200 ok)
        ("hnsw.m=-1", {**BASE, "hnsw_config": {"m": -1}}, True, "m"),
        ("hnsw.m=0 (spec min, allowed)", {**BASE, "hnsw_config": {"m": 0}}, False, None),
        ("hnsw.m=-100", {**BASE, "hnsw_config": {"m": -100}}, True, "m"),
        ("hnsw.m='16' string", {**BASE, "hnsw_config": {"m": "16"}}, True, "m"),
        # constraint 002: ef_construct >= 4 -> 3 must be rejected
        ("hnsw.ef_construct=3", {**BASE, "hnsw_config": {"ef_construct": 3}}, True, "ef_construct"),
        ("hnsw.ef_construct=4 (min, allowed)", {**BASE, "hnsw_config": {"ef_construct": 4}}, False, None),
        ("hnsw.ef_construct=0", {**BASE, "hnsw_config": {"ef_construct": 0}}, True, "ef_construct"),
        ("hnsw.ef_construct=-1", {**BASE, "hnsw_config": {"ef_construct": -1}}, True, "ef_construct"),
        # constraint 003: full_scan_threshold >= 0 (create)
        ("hnsw.full_scan_threshold=-1", {**BASE, "hnsw_config": {"full_scan_threshold": -1}}, True, "full_scan"),
        ("hnsw.full_scan_threshold=0 (min, allowed)", {**BASE, "hnsw_config": {"full_scan_threshold": 0}}, False, None),
        ("hnsw.full_scan_threshold=-10", {**BASE, "hnsw_config": {"full_scan_threshold": -10}}, True, "full_scan"),
    ]
    defect = False
    counter = 0
    for name, payload, should_reject, hint in cases:
        counter += 1
        cname = f"bnd_crt_hn_{counter}"
        status, body, raw = safe_request("PUT", f"/collections/{cname}", json=payload)
        print(f"CASE {name}: status={status} body={raw[:300]}")
        if status == 0:
            print("VERDICT: SCRIPT_ERROR — connection failed")
            return
        if should_reject:
            if status in (200, 201):
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {name} accepted with {status}")
                defect = True
            elif status in (400, 422) and hint and hint.lower() not in raw.lower():
                print(f"NOTE Type2 — {name} rejected but error lacks '{hint}': {raw[:200]}")
        else:
            # allowed min value: 200 expected; also verify persisted value via describe
            if status in (200, 201):
                s2, b2, raw2 = safe_request("GET", f"/collections/{cname}")
                print(f"  DESCRIBE: {raw2[:400]}")
            else:
                print(f"NOTE — {name} spec-min rejected with {status} (possible over-strict validation)")
        try:
            safe_request("DELETE", f"/collections/{cname}")
        except Exception:
            pass
    if not defect:
        print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        test_hnsw_ranges()
    finally:
        pass
