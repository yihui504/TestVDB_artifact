#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.2
Attack: boundary
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

def safe_request(method, endpoint, json=None, timeout=10):
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
        # Ignore 404 (not exists) and other errors during cleanup
    except Exception:
        pass

def test_boundary():
    """
    Test: hnsw_config.m boundary values (constraint: m ∈ [2, 100])
    Strategy: Attack min-1, min, min+1, max-1, max, max+1 boundaries
    """
    collection_name = "test_boundary_m_001"

    # Cleanup first
    cleanup_collection(collection_name)

    # Test 1: m = 1 (min - 1, should fail with 400)
    print("\n=== Test 1: m = 1 (below min) ===")
    payload = {
        "vectors": {
            "size": 128,
            "distance": "Cosine"
        },
        "hnsw_config": {
            "m": 1
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=payload)
    print(f"Status: {status}")
    print(f"Raw: {raw[:200]}")
    if status not in (400, 422):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — m=1 should be rejected (min is 2), got {status}")
        cleanup_collection(collection_name)
        return

    # Test 2: m = 2 (min, should succeed with 200)
    print("\n=== Test 2: m = 2 (valid min) ===")
    payload = {
        "vectors": {
            "size": 128,
            "distance": "Cosine"
        },
        "hnsw_config": {
            "m": 2
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=payload)
    print(f"Status: {status}")
    print(f"Raw: {raw[:200]}")
    if status != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — m=2 should succeed, got {status}")
        cleanup_collection(collection_name)
        return

    # Cleanup for next test
    cleanup_collection(collection_name)

    # Test 3: m = 3 (min + 1, should succeed with 200)
    print("\n=== Test 3: m = 3 (valid min+1) ===")
    payload = {
        "vectors": {
            "size": 128,
            "distance": "Cosine"
        },
        "hnsw_config": {
            "m": 3
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=payload)
    print(f"Status: {status}")
    print(f"Raw: {raw[:200]}")
    if status != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — m=3 should succeed, got {status}")
        cleanup_collection(collection_name)
        return

    # Cleanup for next test
    cleanup_collection(collection_name)

    # Test 4: m = 99 (max - 1, should succeed with 200)
    print("\n=== Test 4: m = 99 (valid max-1) ===")
    payload = {
        "vectors": {
            "size": 128,
            "distance": "Cosine"
        },
        "hnsw_config": {
            "m": 99
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=payload)
    print(f"Status: {status}")
    print(f"Raw: {raw[:200]}")
    if status != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — m=99 should succeed, got {status}")
        cleanup_collection(collection_name)
        return

    # Cleanup for next test
    cleanup_collection(collection_name)

    # Test 5: m = 100 (max, should succeed with 200)
    print("\n=== Test 5: m = 100 (valid max) ===")
    payload = {
        "vectors": {
            "size": 128,
            "distance": "Cosine"
        },
        "hnsw_config": {
            "m": 100
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=payload)
    print(f"Status: {status}")
    print(f"Raw: {raw[:200]}")
    if status != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — m=100 should succeed, got {status}")
        cleanup_collection(collection_name)
        return

    # Cleanup for next test
    cleanup_collection(collection_name)

    # Test 6: m = 101 (max + 1, should fail with 400)
    print("\n=== Test 6: m = 101 (above max) ===")
    payload = {
        "vectors": {
            "size": 128,
            "distance": "Cosine"
        },
        "hnsw_config": {
            "m": 101
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=payload)
    print(f"Status: {status}")
    print(f"Raw: {raw[:200]}")
    if status not in (400, 422):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — m=101 should be rejected (max is 100), got {status}")
        cleanup_collection(collection_name)
        return

    # Final cleanup
    cleanup_collection(collection_name)

    print("\nVERDICT: NO_DEFECT")

if __name__ == "__main__":
    test_boundary()
