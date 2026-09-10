#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: weaviate v1.38.0
Attack: type_boundary
Constraint: vectorIndexConfig.distance readback verification
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
    """Test: vectorIndexConfig.distance readback - verify written value matches read value"""
    collection_name = "test_distance_readback_010"

    # Cleanup: ensure collection doesn't exist
    try:
        safe_request("DELETE", f"/v1/schema/{collection_name}")
    except:
        pass

    # Arrange: Create collection with explicit distance = manhattan
    payload = {
        "class": collection_name,
        "vectorIndexConfig": {
            "distance": "manhattan"
        }
    }

    # Act
    status, body, raw = safe_request("POST", "/v1/schema", json=payload)
    print(f"Create Status: {status}")
    print(f"Create Body: {raw}")

    if status == 0:
        print("VERDICT: SCRIPT_ERROR — connection failed")
        return

    if status not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — collection creation failed with status {status}")
        return

    # Wait for collection to be ready
    time.sleep(1.0)

    # Assert: Read back and verify distance value persisted
    get_status, get_body, get_raw = safe_request("GET", f"/v1/schema/{collection_name}")
    print(f"Get Status: {get_status}")
    print(f"Get Body: {get_raw[:500]}")

    if get_status != 200:
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — Collection created but GET failed with {get_status}")
        # Cleanup
        try:
            safe_request("DELETE", f"/v1/schema/{collection_name}")
        except:
            pass
        return

    # Check if manhattan appears in response
    if "manhattan" in str(get_body).lower():
        print("VERDICT: NO_DEFECT — Distance value persisted correctly")
    else:
        # Check what value was actually stored
        if "cosine" in str(get_body).lower():
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — Requested 'manhattan' but stored 'cosine'")
        elif "l2-squared" in str(get_body).lower():
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — Requested 'manhattan' but stored 'l2-squared'")
        else:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — Requested 'manhattan' but stored unexpected value")
        # Cleanup
        try:
            safe_request("DELETE", f"/v1/schema/{collection_name}")
        except:
            pass
        return

    # Cleanup
    try:
        safe_request("DELETE", f"/v1/schema/{collection_name}")
    except:
        pass

if __name__ == "__main__":
    test_boundary()
