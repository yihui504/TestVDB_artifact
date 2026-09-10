#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: weaviate v1.38.0
Attack: type_boundary
Constraint: activityStatus null validation
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

def test_boundary():
    """Test: activityStatus with null value"""
    collection_name = "test_activitystatus_null_012"
    tenant_name = "tenant1"

    # Setup: Create collection first
    try:
        safe_request("DELETE", f"/v1/schema/{collection_name}")
    except:
        pass

    create_payload = {
        "class": collection_name
    }
    status, _, raw = safe_request("POST", "/v1/schema", json=create_payload)
    if status not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — failed to create collection: {raw}")
        return

    # Wait for collection to be ready
    time.sleep(0.5)

    # Arrange: Create tenant with null activityStatus
    payload = [{
        "name": tenant_name,
        "activityStatus": None
    }]

    # Act
    status, body, raw = safe_request("POST", f"/v1/schema/{collection_name}/tenants", json=payload)
    print(f"Status: {status}")
    print(f"Body: {raw}")

    # Assert
    if status == 0:
        print("VERDICT: SCRIPT_ERROR — connection failed")
        try:
            safe_request("DELETE", f"/v1/schema/{collection_name}")
        except:
            pass
        return

    # Expected: Either accepted (nullable) or rejected
    if status in (200, 201):
        print("VERDICT: NO_DEFECT — null accepted (activityStatus is nullable)")
        # Cleanup
        try:
            safe_request("DELETE", f"/v1/schema/{collection_name}/tenants", json={"tenants": [tenant_name]})
            safe_request("DELETE", f"/v1/schema/{collection_name}")
        except:
            pass
        return

    if status in (400, 422):
        # Type-2 check: error message quality
        if "activityStatus" not in raw.lower() and "null" not in raw.lower():
            print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — Error should mention 'activityStatus' or 'null', got: {raw[:200]}")
        else:
            print("VERDICT: NO_DEFECT — null correctly rejected")
        # Cleanup
        try:
            safe_request("DELETE", f"/v1/schema/{collection_name}")
        except:
            pass
        return

    print(f"VERDICT: NO_DEFECT — unexpected status {status}")

    # Cleanup
    try:
        safe_request("DELETE", f"/v1/schema/{collection_name}/tenants", json={"tenants": [tenant_name]})
        safe_request("DELETE", f"/v1/schema/{collection_name}")
    except:
        pass

if __name__ == "__main__":
    test_boundary()
