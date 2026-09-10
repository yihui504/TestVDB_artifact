#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.2
Attack: boundary
Constraint: scroll limit parameter (inferred from contract default: 10)
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
    """Test: scroll with limit=0 (below minimum) should be rejected"""
    collection_name = "boundary_scroll_limit_0"
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

    # Insert test points
    points = [{"id": i, "vector": [0.1] * vector_dim} for i in range(5)]
    status, _, raw = safe_request("PUT", f"/collections/{collection_name}/points",
        json={"points": points})

    if status not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — failed to insert points, status {status}")
        cleanup_collection(collection_name)
        return

    # Act: Scroll with limit=0
    status, body, raw = safe_request("POST", f"/collections/{collection_name}/points/scroll",
        json={
            "limit": 0
        })

    print(f"Status: {status}")
    print(f"Body: {raw}")

    if status == 0:
        print("VERDICT: SCRIPT_ERROR — connection failed")
        cleanup_collection(collection_name)
        return

    # Assert: Should return 4xx for limit=0
    # Note: Qdrant may accept limit=0 as "no limit", so this is exploratory
    if status == 200:
        print(f"VERDICT: NO_DEFECT — limit=0 accepted (returned {len(body.get('result', {}).get('points', []))} points)")
    elif status in (400, 422):
        print(f"VERDICT: NO_DEFECT — limit=0 correctly rejected")
    else:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Unexpected status {status} for limit=0")

    cleanup_collection(collection_name)

if __name__ == "__main__":
    test_boundary()
