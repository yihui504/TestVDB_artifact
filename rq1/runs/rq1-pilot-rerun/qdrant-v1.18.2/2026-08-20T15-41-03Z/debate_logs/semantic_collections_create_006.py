#!/usr/bin/env python3
"""
Attack: Behavioral Contract test - Create-then-Query visibility
Strategy: behavioral_contract
Endpoint: collections+create
Constraint: qdrant_state_create_collection_001 (Collection creation is atomic - fails if exists)
ExpectedDefect: Type3_RuntimeFailure
"""

import os
import sys
import requests
import time

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

# Test: Create collection with same name twice (should fail second time)
collection_name = "test_semantic_create_duplicate"

# Cleanup first
try:
    safe_request("DELETE", f"/collections/{collection_name}")
except:
    pass

payload = {
    "vectors": {
        "size": 128,
        "distance": "Cosine"
    }
}

# First create - should succeed
CREATE_PATH = f"/collections/{collection_name}"
status1, body1, raw1 = safe_request("PUT", CREATE_PATH, json=payload)
print(f"First Create Status: {status1}")
print(f"First Create Response: {raw1[:200]}")

if status1 != 200:
    print(f"VERDICT: SCRIPT_ERROR — First create failed: {status1}")
    sys.exit(2)

# Verify collection is immediately visible
status_get, body_get, raw_get = safe_request("GET", f"/collections/{collection_name}")
print(f"Get Status (immediate): {status_get}")

if status_get != 200:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Collection not visible immediately after creation")
    sys.exit(1)

# Second create - should fail with 400
time.sleep(0.5)  # Small delay to ensure propagation
status2, body2, raw2 = safe_request("PUT", CREATE_PATH, json=payload)
print(f"Second Create Status: {status2}")
print(f"Second Create Response: {raw2[:500]}")

if status2 != 400:
    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — Duplicate create should fail with 400, got {status2}")
    sys.exit(1)

# Check error message mentions existing collection
error_msg = str(raw2).lower()
if "already" not in error_msg and "exists" not in error_msg:
    print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — Error doesn't mention collection already exists")
    sys.exit(1)

print("VERDICT: NO_DEFECT")

# Cleanup
try:
    safe_request("DELETE", f"/collections/{collection_name}")
except:
    pass
