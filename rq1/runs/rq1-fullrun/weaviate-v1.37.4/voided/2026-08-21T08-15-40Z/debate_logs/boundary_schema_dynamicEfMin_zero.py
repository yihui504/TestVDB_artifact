#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: weaviate v1.37.4
Attack: boundary_value
Constraint: dynamicEfMin lower boundary (zero)
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

def safe_request(method, endpoint, json=None, timeout=10):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text)
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}

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
    """Test: POST /schema with dynamicEfMin=0 (boundary violation)"""
    collection_name = "TestBoundary_dynamicEfMin_zero"

    # Cleanup: ensure fresh start
    try:
        safe_request("DELETE", f"/v1/schema/{collection_name}")
    except:
        pass

    # Arrange: Collection config with dynamicEfMin=0
    payload = {
        "class": collection_name,
        "vectorIndexConfig": {
            "dynamicEfMin": 0,
            "dynamicEfMax": 500
        },
        "vectorizer": "none"
    }

    # Act: Create collection
    status, body, raw = safe_request("POST", "/v1/schema", json=payload)

    print(f"Status: {status}")
    print(f"Body: {raw}")

    # Assert
    if status == 0:
        print("VERDICT: SCRIPT_ERROR — connection failed")
        return

    # Expected: 4xx error (dynamicEfMin should be > 0)
    if status in (200, 201):
        # If accepted, verify the value was actually persisted
        status_get, body_get, raw_get = safe_request("GET", f"/v1/schema/{collection_name}")
        if status_get == 200:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — dynamicEfMin=0 should be rejected, got {status}")
            # Cleanup
            try:
                safe_request("DELETE", f"/v1/schema/{collection_name}")
            except:
                pass
            return

    if status not in (400, 422):
        print(f"VERDICT: NO_DEFECT — dynamicEfMin=0 handled with {status}")

    # Cleanup
    try:
        safe_request("DELETE", f"/v1/schema/{collection_name}")
    except:
        pass

if __name__ == "__main__":
    test_boundary()
