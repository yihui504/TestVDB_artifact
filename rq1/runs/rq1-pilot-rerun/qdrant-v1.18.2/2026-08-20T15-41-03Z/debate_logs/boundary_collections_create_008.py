#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.2
Attack: resource_limit (Strategy 6)
Constraint: qdrant_range_create_collection_001
"""

import requests
import json
import sys
import os

# Windows encoding compatibility
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

AUTH_HEADER = os.environ.get("TESTVDB_AUTH_HEADER", "")

def safe_request(method, endpoint, json=None, timeout=30):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text)
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    if AUTH_HEADER:
        headers["api-key"] = AUTH_HEADER

    try:
        response = requests.request(
            method=method,
            url=url,
            json=json,
            headers=headers,
            timeout=timeout
        )
        status_code = response.status_code
        raw_text = response.text

        try:
            body = response.json()
        except:
            body = raw_text

        return status_code, body, raw_text
    except Exception as e:
        return -1, str(e), str(e)

def cleanup_collection(collection_name):
    """Delete collection if exists, ignoring errors."""
    try:
        status, _, raw = safe_request("DELETE", f"/collections/{collection_name}")
    except Exception:
        pass

def test_boundary():
    """
    Test: Resource limit - extreme hnsw_config.m value
    Strategy: Test with INT_MAX (2147483647) - should not crash/OOM
    """
    collection_name = "test_boundary_reslim_m_008"

    # Cleanup first
    cleanup_collection(collection_name)

    # Test: m = INT_MAX (extreme value, should handle gracefully)
    print("\n=== Test: m = INT_MAX (2147483647) - resource limit test ===")
    payload = {
        "vectors": {
            "size": 128,
            "distance": "Cosine"
        },
        "hnsw_config": {
            "m": 2147483647  # INT_MAX
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=payload, timeout=30)
    print(f"Status: {status}")
    print(f"Raw: {raw[:500]}")

    # Type3 defect = crash/OOM (500/502/503/504 or error messages indicating crash)
    if status in (500, 502, 503, 504):
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Server crashed with m=INT_MAX")
        cleanup_collection(collection_name)
        return

    raw_lower = raw.lower() if raw else ""
    if any(k in raw_lower for k in ["oom", "out of memory", "panic", "capacity overflow", "killed"]):
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — OOM/crash detected with m=INT_MAX")
        cleanup_collection(collection_name)
        return

    # Acceptable outcomes:
    # - 200: accepted (not ideal for production but not a crash defect)
    # - 400/422: properly rejected
    if status == 200:
        print(f"INFO: m=INT_MAX was accepted (returned 200) - this may cause issues later but is not a crash defect")
        print(f"VERDICT: NO_DEFECT (accepted without crash)")
    elif status in (400, 422):
        print(f"INFO: m=INT_MAX was properly rejected")
        print(f"VERDICT: NO_DEFECT (properly rejected)")
    else:
        print(f"VERDICT: UNEXPECTED response {status}")

    # Cleanup
    cleanup_collection(collection_name)

if __name__ == "__main__":
    test_boundary()
