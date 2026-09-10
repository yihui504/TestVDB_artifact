#!/usr/bin/env python3
"""
Attack: Type Coercion test - vectors.distance as integer (should be string enum)
Strategy: type_coercion
Endpoint: collections+create
Constraint: qdrant_type_create_collection_002 (vectors.distance must be string enum)
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

# Test: Create collection with distance as integer (wrong type)
collection_name = "test_semantic_create_distance_int"
CREATE_PATH = f"/collections/{collection_name}"

# Cleanup first
try:
    safe_request("DELETE", f"/collections/{collection_name}")
except:
    pass

payload = {
    "vectors": {
        "size": 128,
        "distance": 1  # Integer instead of string enum
    }
}

status, body, raw = safe_request("PUT", CREATE_PATH, json=payload)
print(f"Status: {status}")
print(f"Response: {raw[:500]}")

if status == 200:
    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — Integer distance=1 accepted instead of string enum")
    sys.exit(1)

if status != 400:
    print(f"VERDICT: SCRIPT_ERROR — Unexpected status {status} for integer distance")
    sys.exit(2)

# Verify error message mentions valid values
error_msg = str(raw).lower()
if "cosine" not in error_msg and "euclidean" not in error_msg:
    print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — Error doesn't list valid distance metrics")
    sys.exit(1)

print("VERDICT: NO_DEFECT")

# Cleanup
try:
    safe_request("DELETE", f"/collections/{collection_name}")
except:
    pass
