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
    """Test: batch_size = 0 (below min) should be rejected"""
    collection_name = "test_boundary_upsert_min"
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

    # Test: upsert with empty batch (0 points)
    upsert_payload = {
        "points": []
    }

    status, _, raw = safe_request("PUT", f"/collections/{collection_name}/points", json=upsert_payload)
    print(f"Status: {status}")
    print(f"Body: {raw}")

    # Cleanup
    try:
        safe_request("DELETE", f"/collections/{collection_name}")
    except:
        pass

    # Expected: 400 or 422 (empty batch should be rejected)
    if status in (400, 422):
        print("VERDICT: NO_DEFECT — Empty batch correctly rejected")
        return

    if status == 0:
        print("VERDICT: SCRIPT_ERROR — Connection failed")
        return

    # Type-2 check: error message quality
    if "batch" not in raw.lower() and "points" not in raw.lower() and "empty" not in raw.lower():
        print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — Error message should mention 'batch' or 'points', got: {raw[:200]}")
        return

    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — Empty batch accepted with status {status}")

if __name__ == "__main__":
    test_boundary()
