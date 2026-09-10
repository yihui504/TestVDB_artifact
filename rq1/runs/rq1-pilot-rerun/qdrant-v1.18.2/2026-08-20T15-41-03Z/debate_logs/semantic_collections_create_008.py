#!/usr/bin/env python3
"""
Attack: Create-then-Query visibility contract - upsert and search immediately
Strategy: behavioral_contract
Endpoint: collections+create (related to qdrant_contract_create_query_001)
Constraint: qdrant_contract_create_query_001 (Create-then-Query visibility)
ExpectedDefect: Type4_StateLogicViolation
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

# Test: Create collection, upsert points, and immediately search
collection_name = "test_semantic_create_visibility"
CREATE_PATH = f"/collections/{collection_name}"
UPSERT_PATH = f"/collections/{collection_name}/points"
SEARCH_PATH = f"/collections/{collection_name}/points/search"

# Cleanup first
try:
    safe_request("DELETE", f"/collections/{collection_name}")
except:
    pass

# Create collection
payload = {
    "vectors": {
        "size": 128,
        "distance": "Cosine"
    }
}

status, body, raw = safe_request("PUT", CREATE_PATH, json=payload)
print(f"Create Status: {status}")
if status != 200:
    print(f"VERDICT: SCRIPT_ERROR — Collection creation failed: {raw[:200]}")
    sys.exit(2)

# Immediate upsert (no delay)
vector_data = [0.1] * 128
upsert_payload = {
    "points": [
        {
            "id": 1,
            "vector": vector_data
        }
    ]
}

status_up, body_up, raw_up = safe_request("PUT", UPSERT_PATH, json=upsert_payload)
print(f"Upsert Status: {status_up}")
if status_up != 200:
    print(f"VERDICT: SCRIPT_ERROR — Upsert failed: {raw_up[:200]}")
    sys.exit(2)

# Immediate search (no delay)
search_payload = {
    "vector": vector_data,
    "limit": 1
}

status_search, body_search, raw_search = safe_request("POST", SEARCH_PATH, json=search_payload)
print(f"Search Status: {status_search}")
print(f"Search Response: {raw_search[:500]}")

if status_search != 200:
    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Search failed after upsert")
    sys.exit(1)

# Check results
results = body_search.get("result", [])
if not isinstance(results, list):
    results = []

if len(results) == 0:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Point not visible immediately after upsert")
    print("Contract violation: Create-then-Query visibility failed")
    sys.exit(1)

# Verify the point ID matches
first_result = results[0]
if isinstance(first_result, dict):
    point_id = first_result.get("id")
else:
    point_id = first_result

if point_id != 1:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Wrong point returned: expected 1, got {point_id}")
    sys.exit(1)

print("VERDICT: NO_DEFECT")

# Cleanup
try:
    safe_request("DELETE", f"/collections/{collection_name}")
except:
    pass
