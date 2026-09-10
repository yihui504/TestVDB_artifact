#!/usr/bin/env python3
"""
Attack: qdrant_contract_create_query_001 (behavioral_contracts::qdrant_contract_create_query_001)
Testing: Create-then-Query visibility contract - newly created collection is immediately visible
Strategy: immediate_visibility
Endpoint: collections+create
Constraint IDs: [behavioral_contracts::qdrant_contract_create_query_001]
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

COLLECTION_NAME = "test_immediate_visibility_cleanup"

# Cleanup
try:
    safe_request("DELETE", f"/collections/{COLLECTION_NAME}")
except Exception:
    pass

# Create collection
create_body = {
    "vectors": {
        "size": 64,
        "distance": "Cosine"
    }
}

status, body, raw = safe_request("PUT", f"/collections/{COLLECTION_NAME}", json=create_body)
print(f"Create collection status: {status}")

if status != 200:
    print(f"VERDICT: SCRIPT_ERROR — Create failed with status {status}")
    sys.exit(2)

# Immediately query without delay - should be visible
status, body, raw = safe_request("GET", f"/collections/{COLLECTION_NAME}")
print(f"Immediate GET status: {status}, raw: {raw[:200]}")

if status != 200:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Created collection not immediately visible (got {status})")
    try:
        safe_request("DELETE", f"/collections/{COLLECTION_NAME}")
    except Exception:
        pass
    sys.exit(1)

# Immediately upsert points
upsert_body = {
    "points": [
        {"id": 1, "vector": [0.1] * 64},
        {"id": 2, "vector": [0.2] * 64}
    ]
}

status, body, raw = safe_request("PUT", f"/collections/{COLLECTION_NAME}/points", json=upsert_body)
print(f"Immediate upsert status: {status}")

if status != 200:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Could not immediately upsert to new collection (got {status})")
    try:
        safe_request("DELETE", f"/collections/{COLLECTION_NAME}")
    except Exception:
        pass
    sys.exit(1)

# Immediately search
search_body = {
    "vector": [0.15] * 64,
    "limit": 10
}

status, body, raw = safe_request("POST", f"/collections/{COLLECTION_NAME}/points/search", json=search_body)
print(f"Immediate search status: {status}, raw: {raw[:200]}")

if status != 200:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Could not immediately search new collection (got {status})")
    try:
        safe_request("DELETE", f"/collections/{COLLECTION_NAME}")
    except Exception:
        pass
    sys.exit(1)

# Verify search results
results = body.get("result", [])
if len(results) == 0:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Empty search results immediately after upsert")
    try:
        safe_request("DELETE", f"/collections/{COLLECTION_NAME}")
    except Exception:
        pass
    sys.exit(1)

# Cleanup
try:
    safe_request("DELETE", f"/collections/{COLLECTION_NAME}")
except Exception:
    pass

print("VERDICT: NO_DEFECT")
sys.exit(0)
