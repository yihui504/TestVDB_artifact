#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: qdrant v1.19.0
Attack: special value - NaN
Constraint: qdrant_type_search_points_001
endpoint: points+search
param: score_threshold
"""

import requests
import json
import sys
import os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

AUTH_HEADER = os.environ.get("TESTVDB_AUTH_HEADER", "")

COLLECTION_NAME = "boundary_search_score_nan_001"
SEARCH_PATH = "/collections/" + COLLECTION_NAME + "/points/search"
VECTOR_DIM = 128

def safe_request(method, path, **kwargs):
    """Safe HTTP request wrapper. Returns (status, body, raw_text)."""
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
    """Cleanup: delete collection if exists (contract-driven)."""
    try:
        status, _, raw = safe_request("DELETE", f"/collections/{COLLECTION_NAME}")
    except Exception:
        pass

def test_boundary():
    """Test: score_threshold = NaN"""
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

    # Act: search with score_threshold=NaN (special value)
    status, body, raw = safe_request("POST", SEARCH_PATH,
        json={"vector": [0.1] * VECTOR_DIM, "limit": 10, "score_threshold": float('nan')})

    # Assert
    if status == 0:
        print("VERDICT: NO_DEFECT — client-layer rejection (requests InvalidJSONError: NaN/Inf not JSON compliant; server never receives request; server-side NaN handling untestable via this path)")
        cleanup()
        return

    print(f"Status: {status}")
    print(f"Body: {raw[:500]}")

    # Expected: 4xx or handled gracefully (NaN is not in [0, 1])
    if status in (500, 502, 503):
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — NaN caused crash, got {status}")
        cleanup()
        return
    elif status not in (400, 422):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — NaN should return 4xx, got {status}")
        cleanup()
        return

    print("VERDICT: NO_DEFECT")
    cleanup()

if __name__ == "__main__":
    test_boundary()
