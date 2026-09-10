#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.19.0
Attack: boundary - min-1 violation
Constraint: qdrant_range_search_points_001
endpoint: points+search
param: limit
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
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

AUTH_HEADER = os.environ.get("TESTVDB_AUTH_HEADER", "")

COLLECTION_NAME = "boundary_search_limit_001"
SEARCH_PATH = "/collections/" + COLLECTION_NAME + "/points/search"
VECTOR_DIM = 128

def safe_request(method, path, **kwargs):
    """Safe HTTP request wrapper (contract-driven). Returns (status, body, raw_text)."""
    url = BASE_URL + path
    headers = kwargs.pop('headers', {})
    if AUTH_HEADER:
        headers['api-key'] = AUTH_HEADER
    headers['Content-Type'] = 'application/json'

    try:
        if method == "GET":
            resp = requests.get(url, headers=headers, timeout=30)
        elif method == "POST":
            data = kwargs.get('data')
            json_data = kwargs.get('json')
            if data is not None:
                resp = requests.post(url, headers=headers, data=data, timeout=30)
            else:
                resp = requests.post(url, headers=headers, json=json_data, timeout=30)
        elif method == "PUT":
            resp = requests.put(url, headers=headers, json=kwargs.get('json'), timeout=30)
        elif method == "DELETE":
            resp = requests.delete(url, headers=headers, timeout=30)
        else:
            return 0, None, f"Unsupported method: {method}"

        try:
            body = resp.json()
        except:
            body = None

        return resp.status_code, body, resp.text
    except requests.exceptions.ConnectionError:
        return 0, None, "Connection failed"
    except requests.exceptions.Timeout:
        return 0, None, "Request timeout"
    except Exception as e:
        return 0, None, str(e)

def cleanup():
    """Cleanup: delete collection if exists (contract-driven cleanup - must be wrapped)."""
    try:
        status, _, raw = safe_request("DELETE", f"/collections/{COLLECTION_NAME}")
    except Exception:
        pass

def test_boundary():
    """Test: limit = 0 (min-1 violation for range [1, 1000])"""
    # Arrange: setup
    cleanup()
    create_status, _, create_raw = safe_request("PUT", f"/collections/{COLLECTION_NAME}",
        json={"vectors": {"size": VECTOR_DIM, "distance": "Cosine"}})
    print(f"Setup create collection: {create_status} - {create_raw[:200]}")

    if create_status not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — Failed to create collection: {create_status}")
        return

    # Insert test point
    upsert_status, _, upsert_raw = safe_request("PUT", f"/collections/{COLLECTION_NAME}/points",
        json={"points": [{"id": 1, "vector": [0.1] * VECTOR_DIM}]})
    print(f"Setup insert point: {upsert_status} - {upsert_raw[:200]}")

    if upsert_status not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — Failed to insert point: {upsert_status}")
        cleanup()
        return

    # Act: search with limit=0 (below minimum)
    status, body, raw = safe_request("POST", SEARCH_PATH,
        json={"vector": [0.1] * VECTOR_DIM, "limit": 0})

    # Assert
    if status == 0:
        print("VERDICT: SCRIPT_ERROR — connection failed")
        cleanup()
        return

    print(f"Status: {status}")
    print(f"Body: {raw[:500]}")

    # Expected: 4xx (limit must be >= 1)
    if status not in (400, 422):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — limit=0 should return 4xx, got {status}")
        cleanup()
        return

    # Type-2: error message quality
    raw_lower = raw.lower()
    if "limit" not in raw_lower and "parameter" not in raw_lower:
        print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — error message should mention 'limit', got: {raw[:200]}")
        cleanup()
        return

    print("VERDICT: NO_DEFECT")
    cleanup()

if __name__ == "__main__":
    test_boundary()
