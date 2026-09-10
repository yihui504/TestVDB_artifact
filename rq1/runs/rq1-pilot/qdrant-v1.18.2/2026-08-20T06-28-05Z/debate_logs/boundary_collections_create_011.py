#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.2
Attack: malformed_input
Constraint: qdrant_type_create_collection_001
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

def safe_request(method, endpoint, data=None, timeout=10):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text)
    Note: data parameter for raw bytes (not json)
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    if AUTH_HEADER:
        headers["Authorization"] = AUTH_HEADER

    try:
        response = requests.request(
            method=method,
            url=url,
            data=data,
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
    """Test: malformed JSON (trailing comma) - parser robustness"""
    collection_name = "boundary_test"

    # Cleanup before test
    cleanup_collection(collection_name)

    # Act: Send malformed JSON with trailing comma
    raw_body = b'{"vectors": {"size": 128, "distance": "Cosine",},}'  # trailing comma

    status, body, raw = safe_request("PUT", f"/collections/{collection_name}",
        data=raw_body, timeout=10)

    print(f"Status: {status}")
    print(f"Body: {raw[:500]}")

    if status == 0:
        print("VERDICT: SCRIPT_ERROR — connection failed")
        return

    # Type3 check: 5xx/panic from malformed JSON = defect
    if status in (500, 502, 503, 504):
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — malformed JSON triggered server crash (5xx)")
        return
    elif any(k in raw.lower() for k in ["panic", "internal", "serde", "parse"]):
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — malformed JSON triggered parser panic")
        return
    elif status in (400, 422):
        print(f"VERDICT: NO_DEFECT — malformed JSON correctly rejected")

    # Cleanup after test
    cleanup_collection(collection_name)

if __name__ == "__main__":
    test_boundary()
