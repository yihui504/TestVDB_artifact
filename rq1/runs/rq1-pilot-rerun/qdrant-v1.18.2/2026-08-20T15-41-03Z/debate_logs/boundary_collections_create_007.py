#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.2
Attack: boundary
Contract: qdrant_contract_create_query_001
"""

import requests
import json
import sys
import os
import time

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
    Test: Create-then-Query visibility contract
    Strategy: Create collection and immediately query, should be visible without delay
    """
    collection_name = "test_boundary_visibility_007"

    # Cleanup first
    cleanup_collection(collection_name)

    # Test 1: Create collection
    print("\n=== Test 1: Create collection ===")
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
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Collection creation should succeed, got {status}")
        cleanup_collection(collection_name)
        return

    # Test 2: Immediately query collection (no delay)
    print("\n=== Test 2: Query collection immediately (no delay) ===")
    status2, body2, raw2 = safe_request("GET", f"/collections/{collection_name}")
    print(f"Status: {status2}")
    print(f"Raw: {raw2[:200]}")
    if status2 != 200:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Collection should be immediately visible, got {status2}")
        cleanup_collection(collection_name)
        return

    # Test 3: Upsert point and immediately search
    print("\n=== Test 3: Upsert point ===")
    point_payload = {
        "points": [
            {
                "id": 1,
                "vector": [0.1] * 128,
                "payload": {"test": "data"}
            }
        ]
    }
    status3, body3, raw3 = safe_request("PUT", f"/collections/{collection_name}/points", json=point_payload)
    print(f"Status: {status3}")
    print(f"Raw: {raw3[:200]}")
    if status3 != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Point upsert should succeed, got {status3}")
        cleanup_collection(collection_name)
        return

    # Test 4: Immediately search for the point
    print("\n=== Test 4: Search immediately after upsert ===")
    search_payload = {
        "vector": [0.1] * 128,
        "limit": 10
    }
    status4, body4, raw4 = safe_request("POST", f"/collections/{collection_name}/points/search", json=search_payload)
    print(f"Status: {status4}")
    print(f"Raw: {raw4[:300]}")
    if status4 != 200:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Search should succeed immediately after upsert, got {status4}")
        cleanup_collection(collection_name)
        return

    # Verify point was found
    results = body4.get("result", []) if isinstance(body4, dict) else []
    if not results or len(results) == 0:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Upserted point should be immediately searchable")
    else:
        print(f"Found {len(results)} result(s)")

    # Test 5: Check collection in list
    print("\n=== Test 5: List collections ===")
    status5, body5, raw5 = safe_request("GET", "/collections")
    print(f"Status: {status5}")
    if status5 == 200:
        collections = body5.get("result", {}).get("collections", []) if isinstance(body5, dict) else []
        collection_names = [c.get("name") for c in collections] if isinstance(collections, list) else []
        if collection_name not in collection_names:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Collection should appear in list")
            print(f"Available collections: {collection_names}")
        else:
            print(f"Collection found in list: {collection_name}")
    else:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — List collections should succeed, got {status5}")

    # Final cleanup
    cleanup_collection(collection_name)

    print("\nVERDICT: NO_DEFECT")

if __name__ == "__main__":
    test_boundary()
