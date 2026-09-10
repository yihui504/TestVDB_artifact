#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant 1.18.0
Attack: boundary_value (strategy 1) — strict_mode_config.max_resident_memory_percent IN [1,100]
Constraint: qdrant_range_collections_create_004
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


def smc(v):
    return {**BASE, "strict_mode_config": {"enabled": True, "max_resident_memory_percent": v}}


def test_strict_mode_range():
    cases = [
        ("max_resident_memory_percent=0 (below min 1)", smc(0), True),
        ("max_resident_memory_percent=1 (min, allowed)", smc(1), False),
        ("max_resident_memory_percent=100 (max, allowed)", smc(100), False),
        ("max_resident_memory_percent=101 (above max)", smc(101), True),
        ("max_resident_memory_percent=-5", smc(-5), True),
        ("max_resident_memory_percent=1e9", smc(1000000000), True),
        ("max_resident_memory_percent=50.5 float", smc(50.5), False),
        ("max_resident_memory_percent='50' string", smc("50"), True),
        ("max_resident_memory_percent=null", {**BASE, "strict_mode_config": {"enabled": True, "max_resident_memory_percent": None}}, True),
    ]
    defect = False
    counter = 0
    for name, payload, should_reject in cases:
        counter += 1
        cname = f"bnd_crt_sm_{counter}"
        status, body, raw = safe_request("PUT", f"/collections/{cname}", json=payload)
        print(f"CASE {name}: status={status} body={raw[:300]}")
        if status == 0:
            print("VERDICT: SCRIPT_ERROR — connection failed")
            return
        if should_reject and status in (200, 201):
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {name} accepted with {status}")
            defect = True
        elif not should_reject and status in (200, 201):
            s2, b2, raw2 = safe_request("GET", f"/collections/{cname}")
            print(f"  DESCRIBE: {raw2[:400]}")
        try:
            safe_request("DELETE", f"/collections/{cname}")
        except Exception:
            pass
    if not defect:
        print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    try:
        test_strict_mode_range()
    finally:
        pass
