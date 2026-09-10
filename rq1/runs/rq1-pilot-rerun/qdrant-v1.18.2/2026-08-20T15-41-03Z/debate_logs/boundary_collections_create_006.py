#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.2
Attack: boundary
Constraint: qdrant_state_create_collection_001
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
    Test: Collection creation atomicity (constraint: must fail if collection already exists)
    Strategy: Create same collection twice, second should fail
    """
    collection_name = "test_boundary_atomic_006"

    # Cleanup first
    cleanup_collection(collection_name)

    # Test 1: Create collection (should succeed with 200)
    print("\n=== Test 1: Create collection (first time, should succeed) ===")
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
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — First creation should succeed, got {status}")
        cleanup_collection(collection_name)
        return

    # Test 2: Create same collection again (should fail with 400)
    print("\n=== Test 2: Create same collection again (should fail) ===")
    status2, body2, raw2 = safe_request("PUT", f"/collections/{collection_name}", json=payload)
    print(f"Status: {status2}")
    print(f"Raw: {raw2[:200]}")
    if status2 not in (400, 409):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — Duplicate creation should be rejected with 400/409, got {status2}")
        cleanup_collection(collection_name)
        return

    # Test 3: Verify collection still exists (GET should succeed)
    print("\n=== Test 3: Verify collection exists ===")
    status3, body3, raw3 = safe_request("GET", f"/collections/{collection_name}")
    print(f"Status: {status3}")
    if status3 != 200:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Collection should still exist after failed duplicate create")

    # Test 4: Delete and recreate (should succeed)
    print("\n=== Test 4: Delete and recreate (should succeed) ===")
    cleanup_collection(collection_name)

    status4, body4, raw4 = safe_request("PUT", f"/collections/{collection_name}", json=payload)
    print(f"Status: {status4}")
    print(f"Raw: {raw4[:200]}")
    if status4 != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Recreation after delete should succeed, got {status4}")
        cleanup_collection(collection_name)
        return

    # Final cleanup
    cleanup_collection(collection_name)

    print("\nVERDICT: NO_DEFECT")

if __name__ == "__main__":
    test_boundary()
