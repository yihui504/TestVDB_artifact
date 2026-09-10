#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: weaviate v1.38.0
Attack: type_boundary
Constraint: activityStatus case sensitivity (lowercase hot)
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
    """Test: activityStatus with lowercase 'hot' (valid enum but wrong case)"""
    collection_name = "test_activitystatus_case_014"
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

    # Arrange: Test lowercase variant of valid enum
    payload = [{
        "name": tenant_name,
        "activityStatus": "hot"  # Valid enum value HOT, test case sensitivity
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

    # Expected: Either accepted (case-insensitive) or rejected (case-sensitive)
    if status in (200, 201):
        print("VERDICT: NO_DEFECT — 'hot' accepted (enum is case-insensitive)")
        # Cleanup
        try:
            safe_request("DELETE", f"/v1/schema/{collection_name}/tenants", json={"tenants": [tenant_name]})
            safe_request("DELETE", f"/v1/schema/{collection_name}")
        except:
            pass
        return

    if status in (400, 422):
        # Check if rejection is due to case sensitivity
        if "case" in raw.lower() or "invalid" in raw.lower():
            print("VERDICT: NO_DEFECT — Correctly rejected, enum is case-sensitive")
        else:
            print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — Rejection without clear case/enum error: {raw[:200]}")
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
