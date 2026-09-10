#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: weaviate v1.38.0
Attack: type_boundary
Constraint: vectorIndexConfig.distance empty string
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
    """Test: vectorIndexConfig.distance with empty string"""
    collection_name = "test_distance_empty_009"

    # Cleanup: ensure collection doesn't exist
    try:
        safe_request("DELETE", f"/v1/schema/{collection_name}")
    except:
        pass

    # Arrange: Create collection with empty distance string
    payload = {
        "class": collection_name,
        "vectorIndexConfig": {
            "distance": ""
        }
    }

    # Act
    status, body, raw = safe_request("POST", "/v1/schema", json=payload)
    print(f"Status: {status}")
    print(f"Body: {raw}")

    # Assert
    if status == 0:
        print("VERDICT: SCRIPT_ERROR — connection failed")
        return

    # Expected: 4xx client error for empty enum value
    if status not in (400, 422):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — Empty distance accepted, got {status}")
        # Cleanup
        try:
            safe_request("DELETE", f"/v1/schema/{collection_name}")
        except:
            pass
        return

    # Type-2 check: error message quality
    if "distance" not in raw.lower() and "enum" not in raw.lower():
        print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — Error should mention 'distance' or 'enum', got: {raw[:200]}")
        return

    print("VERDICT: NO_DEFECT")

    # Cleanup
    try:
        safe_request("DELETE", f"/v1/schema/{collection_name}")
    except:
        pass

if __name__ == "__main__":
    test_boundary()
