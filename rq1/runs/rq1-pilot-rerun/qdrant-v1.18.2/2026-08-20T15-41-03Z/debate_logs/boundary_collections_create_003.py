#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.2
Attack: boundary
Constraint: qdrant_type_create_collection_001
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
    Test: vectors.size boundary and type values (constraint: size > 0, integer)
    Strategy: Attack negative, zero, type coercion (float, string)
    """
    collection_name = "test_boundary_size_003"

    # Cleanup first
    cleanup_collection(collection_name)

    # Test 1: size = 0 (should fail with 400)
    print("\n=== Test 1: size = 0 (zero, should fail) ===")
    payload = {
        "vectors": {
            "size": 0,
            "distance": "Cosine"
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=payload)
    print(f"Status: {status}")
    print(f"Raw: {raw[:200]}")
    if status not in (400, 422):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — size=0 should be rejected, got {status}")
        cleanup_collection(collection_name)
        return

    # Test 2: size = -1 (negative, should fail with 400)
    print("\n=== Test 2: size = -1 (negative, should fail) ===")
    payload = {
        "vectors": {
            "size": -1,
            "distance": "Cosine"
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=payload)
    print(f"Status: {status}")
    print(f"Raw: {raw[:200]}")
    if status not in (400, 422):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — size=-1 should be rejected, got {status}")
        cleanup_collection(collection_name)
        return

    # Test 3: size = 1 (valid min positive integer)
    print("\n=== Test 3: size = 1 (valid min) ===")
    payload = {
        "vectors": {
            "size": 1,
            "distance": "Cosine"
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=payload)
    print(f"Status: {status}")
    print(f"Raw: {raw[:200]}")
    if status != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — size=1 should succeed, got {status}")
        cleanup_collection(collection_name)
        return

    # Cleanup for next test
    cleanup_collection(collection_name)

    # Test 4: size = 128.5 (float, should fail or truncate - test expects rejection)
    print("\n=== Test 4: size = 128.5 (float type, should fail) ===")
    payload = {
        "vectors": {
            "size": 128.5,
            "distance": "Cosine"
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=payload)
    print(f"Status: {status}")
    print(f"Raw: {raw[:200]}")
    # Qdrant might truncate float to int or reject it; either is acceptable
    # Only defect if it accepts and stores as float (type confusion)
    if status == 200:
        # Verify it was stored as int, not float
        status_get, body_get, raw_get = safe_request("GET", f"/collections/{collection_name}")
        if status_get == 200:
            stored_size = body_get.get("result", {}).get("config", {}).get("params", {}).get("vectors", {}).get("size")
            if stored_size == 128.5:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — size stored as float 128.5 instead of int")
                cleanup_collection(collection_name)
                return
    elif status not in (400, 422):
        print(f"VERDICT: UNEXPECTED — size=128.5 got unexpected status {status}")

    # Cleanup for next test
    cleanup_collection(collection_name)

    # Test 5: size = "128" (string type, should fail)
    print("\n=== Test 5: size = '128' (string type, should fail) ===")
    payload = {
        "vectors": {
            "size": "128",
            "distance": "Cosine"
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=payload)
    print(f"Status: {status}")
    print(f"Raw: {raw[:200]}")
    if status not in (400, 422):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — size='128' (string) should be rejected, got {status}")
        cleanup_collection(collection_name)
        return

    # Test 6: size = null (null, should fail)
    print("\n=== Test 6: size = null (null, should fail) ===")
    payload = {
        "vectors": {
            "size": None,
            "distance": "Cosine"
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=payload)
    print(f"Status: {status}")
    print(f"Raw: {raw[:200]}")
    if status not in (400, 422):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — size=null should be rejected, got {status}")
        cleanup_collection(collection_name)
        return

    # Final cleanup
    cleanup_collection(collection_name)

    print("\nVERDICT: NO_DEFECT")

if __name__ == "__main__":
    test_boundary()
