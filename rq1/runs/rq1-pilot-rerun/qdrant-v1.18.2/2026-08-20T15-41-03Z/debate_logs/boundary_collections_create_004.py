#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.2
Attack: boundary
Constraint: qdrant_type_create_collection_002
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
    Test: vectors.distance enum constraint (must be: Cosine, Euclidean, Dot, Manhattan)
    Strategy: Test valid values and invalid variants
    """
    collection_name = "test_boundary_dist_004"

    # Cleanup first
    cleanup_collection(collection_name)

    # Test 1: distance = "Cosine" (valid)
    print("\n=== Test 1: distance = 'Cosine' (valid) ===")
    payload = {
        "vectors": {
            "size": 128,
            "distance": "Cosine"
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=payload)
    print(f"Status: {status}")
    print(f"Raw: {raw[:200]}")
    if status != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — 'Cosine' should succeed, got {status}")
        cleanup_collection(collection_name)
        return

    # Cleanup
    cleanup_collection(collection_name)

    # Test 2: distance = "Euclidean" (valid)
    print("\n=== Test 2: distance = 'Euclidean' (valid) ===")
    payload = {
        "vectors": {
            "size": 128,
            "distance": "Euclidean"
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=payload)
    print(f"Status: {status}")
    print(f"Raw: {raw[:200]}")
    if status != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — 'Euclidean' should succeed, got {status}")
        cleanup_collection(collection_name)
        return

    # Cleanup
    cleanup_collection(collection_name)

    # Test 3: distance = "Dot" (valid)
    print("\n=== Test 3: distance = 'Dot' (valid) ===")
    payload = {
        "vectors": {
            "size": 128,
            "distance": "Dot"
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=payload)
    print(f"Status: {status}")
    print(f"Raw: {raw[:200]}")
    if status != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — 'Dot' should succeed, got {status}")
        cleanup_collection(collection_name)
        return

    # Cleanup
    cleanup_collection(collection_name)

    # Test 4: distance = "Manhattan" (valid)
    print("\n=== Test 4: distance = 'Manhattan' (valid) ===")
    payload = {
        "vectors": {
            "size": 128,
            "distance": "Manhattan"
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=payload)
    print(f"Status: {status}")
    print(f"Raw: {raw[:200]}")
    if status != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — 'Manhattan' should succeed, got {status}")
        cleanup_collection(collection_name)
        return

    # Cleanup
    cleanup_collection(collection_name)

    # Test 5: distance = "cosine" (lowercase, invalid - should fail)
    print("\n=== Test 5: distance = 'cosine' (lowercase, should fail) ===")
    payload = {
        "vectors": {
            "size": 128,
            "distance": "cosine"
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=payload)
    print(f"Status: {status}")
    print(f"Raw: {raw[:200]}")
    if status not in (400, 422):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — 'cosine' (lowercase) should be rejected, got {status}")
        cleanup_collection(collection_name)
        return

    # Test 6: distance = "COSINE" (uppercase, invalid - should fail)
    print("\n=== Test 6: distance = 'COSINE' (uppercase, should fail) ===")
    payload = {
        "vectors": {
            "size": 128,
            "distance": "COSINE"
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=payload)
    print(f"Status: {status}")
    print(f"Raw: {raw[:200]}")
    if status not in (400, 422):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — 'COSINE' (uppercase) should be rejected, got {status}")
        cleanup_collection(collection_name)
        return

    # Test 7: distance = "InvalidMetric" (invalid - should fail)
    print("\n=== Test 7: distance = 'InvalidMetric' (invalid, should fail) ===")
    payload = {
        "vectors": {
            "size": 128,
            "distance": "InvalidMetric"
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=payload)
    print(f"Status: {status}")
    print(f"Raw: {raw[:200]}")
    if status not in (400, 422):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — 'InvalidMetric' should be rejected, got {status}")
        cleanup_collection(collection_name)
        return

    # Test 8: distance = "" (empty string, invalid - should fail)
    print("\n=== Test 8: distance = '' (empty string, should fail) ===")
    payload = {
        "vectors": {
            "size": 128,
            "distance": ""
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=payload)
    print(f"Status: {status}")
    print(f"Raw: {raw[:200]}")
    if status not in (400, 422):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — empty distance should be rejected, got {status}")
        cleanup_collection(collection_name)
        return

    # Test 9: distance = null (null, invalid - should fail)
    print("\n=== Test 9: distance = null (null, should fail) ===")
    payload = {
        "vectors": {
            "size": 128,
            "distance": None
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=payload)
    print(f"Status: {status}")
    print(f"Raw: {raw[:200]}")
    if status not in (400, 422):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — null distance should be rejected, got {status}")
        cleanup_collection(collection_name)
        return

    # Final cleanup
    cleanup_collection(collection_name)

    print("\nVERDICT: NO_DEFECT")

if __name__ == "__main__":
    test_boundary()
