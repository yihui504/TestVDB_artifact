#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: boundary (strategy 7)
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

def safe_request(method, path, **kwargs):
    """Contract-driven safe request wrapper for Qdrant REST API."""
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    if AUTH_HEADER:
        headers["api-key"] = AUTH_HEADER

    try:
        resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        raw = resp.text
        try:
            body = resp.json()
        except:
            body = raw
        return resp.status_code, body, raw
    except Exception as e:
        return 0, str(e), str(e)

def test_boundary():
    """Test: Upsert with NUL byte in point ID (malformed input / special char fuzzing)"""
    collection_name = "test_boundary_upsert_malformed_001"
    dim = 128

    # Arrange: Setup
    try:
        safe_request("DELETE", f"/collections/{collection_name}")
    except:
        pass

    create_status, _, raw = safe_request("PUT", f"/collections/{collection_name}",
        json={"vectors": {"size": dim, "distance": "Cosine"}})
    if create_status not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — Collection setup failed (status {create_status}): {raw}")
        return

    # Act: Upsert with NUL byte in point ID (using raw bytes)
    # Strategy 7: malformed input / special char fuzzing
    raw_body = '{"points": [{"id": "a\\u0000b", "vector": [0.1]*128}]}'.replace("[0.1]*128", str([0.1]*dim)).encode("utf-8")
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}/points",
        data=raw_body)

    # Cleanup
    try:
        safe_request("DELETE", f"/collections/{collection_name}")
    except:
        pass

    # Assert
    print(f"Status: {status}")
    print(f"Body: {raw}")

    if status == 0:
        print("VERDICT: SCRIPT_ERROR — connection failed")
        return

    # Expected for NUL/ malformed input: 4xx (clean rejection) or 5xx (parser panic)
    if status in (500, 502, 503) or any(k in raw.lower() for k in ["panic", "internal", "serde", "utf", "decode"]):
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — NUL/ malformed input triggered 5xx/parser panic")
    elif status == 200:
        # Silent accept - need doc verification to judge Type1
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSilentAccept) — NUL byte accepted without rejection (pending doc verification)")
    elif status in (400, 422):
        print(f"VERDICT: NO_DEFECT — NUL byte correctly rejected")
    else:
        print(f"VERDICT: NO_DEFECT — Unexpected status {status}, but not a crash")

if __name__ == "__main__":
    test_boundary()
