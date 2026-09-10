#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.2
Attack: boundary
Constraint: qdrant_range_create_collection_003
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
    except Exception:
        pass

def test_boundary():
    """
    Test: optimizers_config.indexing_threshold boundary (constraint: >= 0)
    Strategy: Test negative, zero, positive values
    """
    collection_name = "test_boundary_idx_005"

    # Cleanup first
    cleanup_collection(collection_name)

    # Test 1: indexing_threshold = -1 (negative, should fail with 400)
    print("\n=== Test 1: indexing_threshold = -1 (negative, should fail) ===")
    payload = {
        "vectors": {
            "size": 128,
            "distance": "Cosine"
        },
        "optimizers_config": {
            "indexing_threshold": -1
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=payload)
    print(f"Status: {status}")
    print(f"Raw: {raw[:200]}")
    if status not in (400, 422):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — indexing_threshold=-1 should be rejected, got {status}")
        cleanup_collection(collection_name)
        return

    # Test 2: indexing_threshold = 0 (valid min)
    print("\n=== Test 2: indexing_threshold = 0 (valid min) ===")
    payload = {
        "vectors": {
            "size": 128,
            "distance": "Cosine"
        },
        "optimizers_config": {
            "indexing_threshold": 0
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=payload)
    print(f"Status: {status}")
    print(f"Raw: {raw[:200]}")
    if status != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — indexing_threshold=0 should succeed, got {status}")
        cleanup_collection(collection_name)
        return

    # Cleanup for next test
    cleanup_collection(collection_name)

    # Test 3: indexing_threshold = 1 (positive valid)
    print("\n=== Test 3: indexing_threshold = 1 (positive) ===")
    payload = {
        "vectors": {
            "size": 128,
            "distance": "Cosine"
        },
        "optimizers_config": {
            "indexing_threshold": 1
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=payload)
    print(f"Status: {status}")
    print(f"Raw: {raw[:200]}")
    if status != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — indexing_threshold=1 should succeed, got {status}")
        cleanup_collection(collection_name)
        return

    # Cleanup for next test
    cleanup_collection(collection_name)

    # Test 4: indexing_threshold = 20000 (default valid value)
    print("\n=== Test 4: indexing_threshold = 20000 (default) ===")
    payload = {
        "vectors": {
            "size": 128,
            "distance": "Cosine"
        },
        "optimizers_config": {
            "indexing_threshold": 20000
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=payload)
    print(f"Status: {status}")
    print(f"Raw: {raw[:200]}")
    if status != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — indexing_threshold=20000 should succeed, got {status}")
        cleanup_collection(collection_name)
        return

    # Cleanup for next test
    cleanup_collection(collection_name)

    # Test 5: indexing_threshold = 1000000 (large valid value)
    print("\n=== Test 5: indexing_threshold = 1000000 (large) ===")
    payload = {
        "vectors": {
            "size": 128,
            "distance": "Cosine"
        },
        "optimizers_config": {
            "indexing_threshold": 1000000
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=payload)
    print(f"Status: {status}")
    print(f"Raw: {raw[:200]}")
    if status != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — indexing_threshold=1000000 should succeed, got {status}")
        cleanup_collection(collection_name)
        return

    # Test 6: indexing_threshold = -100 (negative, should fail)
    print("\n=== Test 6: indexing_threshold = -100 (negative) ===")
    payload = {
        "vectors": {
            "size": 128,
            "distance": "Cosine"
        },
        "optimizers_config": {
            "indexing_threshold": -100
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=payload)
    print(f"Status: {status}")
    print(f"Raw: {raw[:200]}")
    if status not in (400, 422):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — indexing_threshold=-100 should be rejected, got {status}")
        cleanup_collection(collection_name)
        return

    # Final cleanup
    cleanup_collection(collection_name)

    print("\nVERDICT: NO_DEFECT")

if __name__ == "__main__":
    test_boundary()
