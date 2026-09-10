#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: boundary (strategy 3)
Constraint: qdrant_type_create_collection_001 + qdrant_range_upsert_points_001
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
    """Test: Upsert with vector dimension mismatch (64 != 128)"""
    collection_name = "test_boundary_upsert_vector_dim_001"
    dim_create = 128
    dim_upsert = 64

    # Arrange: Setup
    try:
        safe_request("DELETE", f"/collections/{collection_name}")
    except:
        pass

    create_status, _, raw = safe_request("PUT", f"/collections/{collection_name}",
        json={"vectors": {"size": dim_create, "distance": "Cosine"}})
    if create_status not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — Collection setup failed (status {create_status}): {raw}")
        return

    # Act: Upsert with wrong dimension
    status, body, raw = safe_request("PUT", f"/collections/{collection_name}/points",
        json={"points": [{"id": 1, "vector": [0.1] * dim_upsert}]})

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

    # Expected: 400 or 422 (dimension mismatch)
    if status not in (400, 422):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — dimension mismatch should be rejected, got {status}")
        return

    # Type-2 check
    if "dimension" not in raw.lower() and "vector" not in raw.lower() and "size" not in raw.lower():
        print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — Error should mention 'dimension' or 'vector' or 'size', got: {raw[:200]}")
        return

    print("VERDICT: NO_DEFECT")

if __name__ == "__main__":
    test_boundary()
