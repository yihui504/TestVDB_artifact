#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.2
Attack: type_confusion (null handling)
Constraint: hnsw_ef null value testing
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
    """Test: hnsw_ef=null should be handled gracefully"""
    collection_name = "boundary_search_hnsw_ef_null"
    vector_dim = 128

    # Setup: Create collection and insert test data
    cleanup_collection(collection_name)

    status, _, raw = safe_request("PUT", f"/collections/{collection_name}",
        json={
            "vectors": {
                "size": vector_dim,
                "distance": "Cosine"
            }
        })

    if status not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — failed to create collection, status {status}")
        return

    # Insert test point
    status, _, raw = safe_request("PUT", f"/collections/{collection_name}/points",
        json={
            "points": [
                {
                    "id": 1,
                    "vector": [0.1] * vector_dim
                }
            ]
        })

    if status not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — failed to insert point, status {status}")
        cleanup_collection(collection_name)
        return

    # Act: Search with hnsw_ef=null
    status, body, raw = safe_request("POST", f"/collections/{collection_name}/points/search",
        json={
            "vector": [0.2] * vector_dim,
            "limit": 10,
            "params": {
                "hnsw_ef": None
            }
        })

    print(f"Status: {status}")
    print(f"Body: {raw}")

    if status == 0:
        print("VERDICT: SCRIPT_ERROR — connection failed")
        cleanup_collection(collection_name)
        return

    # Assert: null hnsw_ef should be handled (rejected or defaulted)
    if status in (500, 502, 503):
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — hnsw_ef=null triggered crash, got {status}")
        cleanup_collection(collection_name)
        return
    elif status in (200, 201):
        # null was defaulted - acceptable behavior
        print(f"VERDICT: NO_DEFECT — hnsw_ef=null defaulted to internal value (status {status})")
    elif status in (400, 422):
        if "hnsw_ef" not in raw.lower() and "ef" not in raw.lower():
            print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — Error should mention parameter, got: {raw[:200]}")
            cleanup_collection(collection_name)
            return
        print(f"VERDICT: NO_DEFECT — hnsw_ef=null properly rejected")
    else:
        print(f"VERDICT: NO_DEFECT — Unexpected status {status}")

    cleanup_collection(collection_name)

if __name__ == "__main__":
    test_boundary()
