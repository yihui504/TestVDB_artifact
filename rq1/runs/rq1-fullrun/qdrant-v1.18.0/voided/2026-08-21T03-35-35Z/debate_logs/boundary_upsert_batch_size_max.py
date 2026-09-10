#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: boundary
Constraint: qdrant_range_upsert_points_001
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

def test_boundary():
    """Test: batch_size = 1001 (above max) should be rejected or handled gracefully"""
    collection_name = "test_boundary_upsert_max"
    vector_dim = 128

    # Setup: delete collection if exists
    try:
        safe_request("DELETE", f"/collections/{collection_name}")
    except:
        pass

    # Create collection
    create_payload = {
        "vectors": {
            "size": vector_dim,
            "distance": "Cosine"
        }
    }
    status, _, raw = safe_request("PUT", f"/collections/{collection_name}", json=create_payload)
    print(f"Create collection status: {status}")
    if status not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — Collection creation failed: {raw}")
        return

    # Test: upsert with 1001 points (above documented max of 1000)
    points = []
    for i in range(1001):
        points.append({
            "id": i,
            "vector": [0.1] * vector_dim
        })

    upsert_payload = {
        "points": points
    }

    status, _, raw = safe_request("PUT", f"/collections/{collection_name}/points", json=upsert_payload)
    print(f"Status: {status}")
    print(f"Body: {raw[:500]}")

    # Cleanup
    try:
        safe_request("DELETE", f"/collections/{collection_name}")
    except:
        pass

    # Expected behaviors:
    # 1. 400/422: explicit rejection (OK)
    # 2. 200: partial or full acceptance (OK, but verify behavior)
    # 3. 500+: crash (DEFECT)
    if status in (500, 502, 503, 504):
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Batch size 1001 triggered crash")
        return

    if status == 0:
        print("VERDICT: SCRIPT_ERROR — Connection failed")
        return

    # Check for OOM or crash indicators in response
    raw_lower = raw.lower()
    if any(k in raw_lower for k in ["out of memory", "oom", "panic", "killed", "capacity overflow"]):
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Batch size 1001 triggered OOM/crash")
        return

    if status in (400, 422):
        print("VERDICT: NO_DEFECT — Batch size > 1000 correctly rejected")
        return

    if status in (200, 201):
        print("VERDICT: NO_DEFECT — Batch size > 1000 accepted (DB may handle larger batches)")
        return

    print(f"VERDICT: NO_DEFECT — Status {status} received")

if __name__ == "__main__":
    test_boundary()
