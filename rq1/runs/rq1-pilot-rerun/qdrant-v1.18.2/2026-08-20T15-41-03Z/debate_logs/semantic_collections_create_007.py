#!/usr/bin/env python3
"""
Attack: Type Coercion test - vectors.size as string "128"
Strategy: type_coercion
Endpoint: collections+create
Constraint: qdrant_type_create_collection_001 (vectors.size must be positive integer)
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

# Test: Create collection with vectors.size as string instead of integer
collection_name = "test_semantic_create_size_string"
CREATE_PATH = f"/collections/{collection_name}"

# Cleanup first
try:
    safe_request("DELETE", f"/collections/{collection_name}")
except:
    pass

payload = {
    "vectors": {
        "size": "128",  # String instead of integer
        "distance": "Cosine"
    }
}

status, body, raw = safe_request("PUT", CREATE_PATH, json=payload)
print(f"Status: {status}")
print(f"Response: {raw[:500]}")

if status == 200:
    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — String size='128' accepted instead of integer")
    sys.exit(1)

if status != 400:
    print(f"VERDICT: SCRIPT_ERROR — Unexpected status {status} for string size")
    sys.exit(2)

# Verify error message mentions type issue
error_msg = str(raw).lower()
if "integer" not in error_msg and "int" not in error_msg and "type" not in error_msg:
    print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — Error doesn't mention type requirement")
    sys.exit(1)

print("VERDICT: NO_DEFECT")

# Cleanup
try:
    safe_request("DELETE", f"/collections/{collection_name}")
except:
    pass
