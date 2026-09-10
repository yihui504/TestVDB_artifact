#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.2
Attack: boundary
Constraint: qdrant_range_create_collection_002
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
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
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
        headers["Authorization"] = AUTH_HEADER

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
    """Cleanup collection - wrapped to prevent exit on failure"""
    try:
        safe_request("DELETE", f"/collections/{collection_name}")
    except Exception:
        pass

def test_boundary():
    """Test: hnsw_config.ef_construct with boundary value 9 (min - 1) should be rejected"""
    collection_name = "boundary_test_ef_construct_9"

    # Cleanup before test
    cleanup_collection(collection_name)

    # Act: Try to create collection with hnsw_config.ef_construct = 9 (below min of 10)
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}",
        json={
            "vectors": {
                "size": 128,
                "distance": "Cosine"
            },
            "hnsw_config": {
                "ef_construct": 9
            }
        })

    print(f"Status: {status}")
    print(f"Body: {raw}")

    if status == 0:
        print("VERDICT: SCRIPT_ERROR — connection failed")
        return

    # Assert: Should return 4xx for ef_construct=9 (contract says ef_construct >= 10)
    if status not in (400, 422):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — hnsw_config.ef_construct=9 should be rejected (contract says ef_construct >= 10), got {status}")
        return

    print("VERDICT: NO_DEFECT")

    # Cleanup after test
    cleanup_collection(collection_name)

if __name__ == "__main__":
    test_boundary()
