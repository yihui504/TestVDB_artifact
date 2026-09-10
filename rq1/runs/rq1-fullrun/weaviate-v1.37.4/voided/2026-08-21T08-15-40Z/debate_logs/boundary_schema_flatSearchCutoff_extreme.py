#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: weaviate v1.37.4
Attack: boundary_value
Constraint: flatSearchCutoff extreme value (DoS/resource limit)
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
    """Test: POST /schema with flatSearchCutoff=2147483647 (extreme value, potential DoS)"""
    collection_name = "TestBoundary_flatSearchCutoff_extreme"

    # Cleanup: ensure fresh start
    try:
        safe_request("DELETE", f"/v1/schema/{collection_name}")
    except:
        pass

    # Arrange: Collection config with extreme flatSearchCutoff value
    payload = {
        "class": collection_name,
        "vectorIndexConfig": {
            "flatSearchCutoff": 2147483647  # INT_MAX
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

    # Expected: 200 (accepted), 400/422 (rejected), or 5xx (DoS/crash - defect)
    if status in (500, 502, 503):
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — flatSearchCutoff=INT_MAX caused crash/5xx")
        # Cleanup
        try:
            safe_request("DELETE", f"/v1/schema/{collection_name}")
        except:
            pass
        return

    if status in (200, 201):
        print(f"VERDICT: NO_DEFECT — flatSearchCutoff=INT_MAX accepted (may be valid upper bound)")
        # Cleanup
        try:
            safe_request("DELETE", f"/v1/schema/{collection_name}")
        except:
            pass
        return

    if status in (400, 422):
        print("VERDICT: NO_DEFECT — flatSearchCutoff=INT_MAX correctly rejected")

    # Cleanup
    try:
        safe_request("DELETE", f"/v1/schema/{collection_name}")
    except:
        pass

if __name__ == "__main__":
    test_boundary()
