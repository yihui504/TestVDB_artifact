#!/usr/bin/env python3
"""
Attack: Type Coercion test - hnsw_config.m as float 16.0
Strategy: type_coercion
Endpoint: collections+create
Constraint: qdrant_type_create_collection_001 (implicit type validation)
ExpectedDefect: Type1_IllegalSuccess
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

# Test: Create collection with hnsw_config.m as float instead of integer
collection_name = "test_semantic_create_m_float"
CREATE_PATH = f"/collections/{collection_name}"

# Cleanup first
try:
    safe_request("DELETE", f"/collections/{collection_name}")
except:
    pass

payload = {
    "vectors": {
        "size": 128,
        "distance": "Cosine"
    },
    "hnsw_config": {
        "m": 16.0  # Float instead of integer
    }
}

status, body, raw = safe_request("PUT", CREATE_PATH, json=payload)
print(f"Status: {status}")
print(f"Response: {raw[:500]}")

if status == 200:
    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — Float m=16.0 accepted instead of integer")
    sys.exit(1)

if status != 400:
    print(f"VERDICT: SCRIPT_ERROR — Unexpected status {status} for float m")
    sys.exit(2)

# Verify error message mentions type issue
error_msg = str(raw).lower()
if "integer" not in error_msg and "int" not in error_msg and "whole number" not in error_msg:
    print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — Error doesn't mention integer requirement")
    sys.exit(1)

print("VERDICT: NO_DEFECT")

# Cleanup
try:
    safe_request("DELETE", f"/collections/{collection_name}")
except:
    pass
