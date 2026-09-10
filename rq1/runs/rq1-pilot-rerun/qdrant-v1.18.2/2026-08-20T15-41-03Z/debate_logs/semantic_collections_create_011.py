#!/usr/bin/env python3
"""
Attack: Illegal Rejection test - valid hnsw_config.m=50 (within range [2, 100])
Strategy: illegal_rejection
Endpoint: collections+create
Constraint: qdrant_range_create_collection_001 (hnsw_config.m in range [2, 100])
ExpectedDefect: Type1_IllegalRejection
"""

import os
import sys
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

def safe_request(method, endpoint, json=None, timeout=10):
    """Safe HTTP request wrapper with unified error handling"""
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(method=method, url=url, json=json, headers=headers, timeout=timeout)
        return response.status_code, response.json(), response.text
    except Exception as e:
        return -1, str(e), str(e)

# Test: Create collection with valid hnsw_config.m values
valid_m_values = [2, 16, 50, 100]

for m_val in valid_m_values:
    collection_name = f"test_semantic_create_m_{m_val}"
    CREATE_PATH = f"/collections/{collection_name}"

    # Cleanup first
    try:
        safe_request("DELETE", CREATE_PATH)
    except:
        pass

    payload = {
        "vectors": {
            "size": 128,
            "distance": "Cosine"
        },
        "hnsw_config": {
            "m": m_val
        }
    }

    status, body, raw = safe_request("PUT", CREATE_PATH, json=payload)
    print(f"m={m_val}, Status: {status}")

    if status != 200:
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) — Valid m={m_val} rejected with status {status}")
        print(f"Response: {raw[:500]}")
        sys.exit(1)

    # Cleanup
    try:
        safe_request("DELETE", CREATE_PATH)
    except:
        pass

print("VERDICT: NO_DEFECT")
