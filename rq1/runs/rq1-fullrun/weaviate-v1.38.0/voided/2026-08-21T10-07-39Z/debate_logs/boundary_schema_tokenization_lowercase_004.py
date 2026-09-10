#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: weaviate v1.38.0
Attack: type_boundary
Constraint: tokenization case sensitivity (lowercase HOT)
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
    """Test: tokenization with lowercase 'word' (valid enum but wrong case)"""
    collection_name = "test_tokenization_case_004"

    # Cleanup: ensure collection doesn't exist
    try:
        safe_request("DELETE", f"/v1/schema/{collection_name}")
    except:
        pass

    # Arrange: Test lowercase variant of valid enum
    payload = {
        "class": collection_name,
        "properties": [{
            "name": "description",
            "dataType": ["text"],
            "tokenization": "word"  # Valid enum value, test case sensitivity
        }]
    }

    # Act
    status, body, raw = safe_request("POST", "/v1/schema", json=payload)
    print(f"Status: {status}")
    print(f"Body: {raw}")

    # Assert
    if status == 0:
        print("VERDICT: SCRIPT_ERROR — connection failed")
        return

    # Expected: Either accepted (case-insensitive) or rejected (case-sensitive)
    if status in (200, 201):
        print("VERDICT: NO_DEFECT — 'word' accepted (enum is case-insensitive)")
        # Cleanup
        try:
            safe_request("DELETE", f"/v1/schema/{collection_name}")
        except:
            pass
        return

    if status in (400, 422):
        # Check if rejection is due to case sensitivity
        if "case" in raw.lower() or "invalid" in raw.lower():
            print("VERDICT: NO_DEFECT — Correctly rejected, enum is case-sensitive")
            return
        else:
            print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — Rejection without clear case/enum error: {raw[:200]}")
            return

    print(f"VERDICT: NO_DEFECT — unexpected status {status}")

    # Cleanup
    try:
        safe_request("DELETE", f"/v1/schema/{collection_name}")
    except:
        pass

if __name__ == "__main__":
    test_boundary()
