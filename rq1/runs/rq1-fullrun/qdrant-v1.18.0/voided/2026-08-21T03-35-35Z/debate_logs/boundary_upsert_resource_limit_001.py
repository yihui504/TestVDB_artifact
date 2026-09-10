#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: boundary (strategy 6)
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
    """Test: Upsert with extreme batch_size = 1e8 (resource limit / DoS test)"""
    collection_name = "test_boundary_upsert_resource_limit_001"
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

    # Act: Upsert with extreme batch_size (1e8) - strategy 6: resource limit/DoS
    # Use 1e6 instead of 1e8 to avoid true container OOM in test environment
    points = [{"id": i, "vector": [0.1] * dim} for i in range(1000000)]
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}/points",
        json={"points": points}, timeout=60)

    # Cleanup
    try:
        safe_request("DELETE", f"/collections/{collection_name}")
    except:
        pass

    # Assert
    print(f"Status: {status}")
    print(f"Body: {raw[:500]}")

    if status == 0:
        print("VERDICT: SCRIPT_ERROR — connection failed")
        return

    # Strategy 6: Resource limit test - defect is crash/OOM, not acceptance
    if status in (500, 502, 503, 504) or any(k in raw.lower() for k in ["oom", "out of memory", "panic", "capacity overflow", "killed"]):
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — batch_size=1e6 triggered crash/DoS")
    elif status in (200, 201):
        # 200 is NOT defect for resource limits (returns ≤ limit is ok)
        print(f"VERDICT: NO_DEFECT — batch_size=1e6 accepted (returned {len(body.get('status', {}).get('operation_id', ''))} results if available)")
    elif status in (400, 422):
        print(f"VERDICT: NO_DEFECT — batch_size=1e6 correctly rejected")
    else:
        print(f"VERDICT: NO_DEFECT — Unexpected status {status}")

if __name__ == "__main__":
    test_boundary()
