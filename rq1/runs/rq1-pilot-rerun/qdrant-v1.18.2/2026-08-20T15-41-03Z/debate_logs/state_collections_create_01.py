#!/usr/bin/env python3
"""
Attack: qdrant_invariant_create_001 (state_invariants::qdrant_invariant_create_001)
Testing: After creating a collection, it should be visible in collection list and retrievable via GET
Strategy: create_consistency
Endpoint: collections+create
Constraint IDs: [state_invariants::qdrant_invariant_create_001]
Source URL: https://api.qdrant.tech/api-reference/collections/create-collection
Doc Version: 1.19.x
Expected Defect Type: Type4_StateLogicViolation
"""

import os
import sys
import time

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

def safe_request(method, endpoint, json=None, timeout=10):
    """Safe HTTP request wrapper with unified error handling."""
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}

    try:
        import requests
        response = requests.request(method, url, json=json, headers=headers, timeout=timeout)
        status_code = response.status_code
        raw_text = response.text
        try:
            body = response.json()
        except:
            body = raw_text
        return status_code, body, raw_text
    except Exception as e:
        return -1, str(e), str(e)

COLLECTION_NAME = "test_state_create_001_cleanup"

# Cleanup: delete collection if exists
try:
    safe_request("DELETE", f"/collections/{COLLECTION_NAME}")
except Exception:
    pass

# Test 1: Create collection with valid parameters
create_body = {
    "vectors": {
        "size": 128,
        "distance": "Cosine"
    }
}

status, body, raw = safe_request("PUT", f"/collections/{COLLECTION_NAME}", json=create_body)
print(f"Create collection status: {status}, raw: {raw[:200]}")

if status != 200:
    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Create collection failed with status {status}")
    sys.exit(1)

# Test 2: Verify collection exists in list
status, body, raw = safe_request("GET", "/collections")
print(f"List collections status: {status}, raw: {raw[:500]}")

if status != 200:
    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — List collections failed with status {status}")
    sys.exit(1)

collections = body.get("result", {}).get("collections", [])
collection_names = [c.get("name") for c in collections]

if COLLECTION_NAME not in collection_names:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Created collection not in list. Collections: {collection_names}")
    sys.exit(1)

# Test 3: Verify get collection succeeds
status, body, raw = safe_request("GET", f"/collections/{COLLECTION_NAME}")
print(f"Get collection status: {status}, raw: {raw[:200]}")

if status != 200:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Get created collection failed with status {status}")
    sys.exit(1)

# Test 4: Verify collection config matches request
result = body.get("result", {})
config = result.get("config", {}).get("params", {})
vectors_config = config.get("vectors", {})

if vectors_config.get("size") != 128 or vectors_config.get("distance") != "Cosine":
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Collection config mismatch. Got: {vectors_config}")
    sys.exit(1)

# Cleanup
try:
    safe_request("DELETE", f"/collections/{COLLECTION_NAME}")
except Exception:
    pass

print("VERDICT: NO_DEFECT")
sys.exit(0)
