#!/usr/bin/env python3
"""
Attack: state_consistency | atomic_creation | repeat_create_400
Strategy: 2 (DELETE后一致性 - 适配CREATE场景)
Endpoint: collections+create
Constraint IDs:
  - assertions::qdrant_behavioral_create_collection_001
  - assertions::qdrant_behavioral_create_collection_002
Source URL: https://api.qdrant.tech/api-reference/collections/create-collection
Doc Version: 1.19.x
Expected Defect Type: Type4_StateLogicViolation
Blindspot: BS-03 (Concurrency Blindness) - inter-request state visibility
"""

import os
import sys
import time
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

def safe_request(method, endpoint, json=None, timeout=10):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text)
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.request(
            method=method,
            url=url,
            json=json,
            headers=headers,
            timeout=timeout
        )
        status_code = response.status_code
        raw_text = response.text

        try:
            body = response.json()
        except:
            body = raw_text

        return status_code, body, raw_text
    except Exception as e:
        return -1, str(e), str(e)

COLL_NAME = "test_state_create_atomic"

# Cleanup: try delete existing collection
try:
    safe_request("DELETE", f"/collections/{COLL_NAME}")
    time.sleep(0.1)
except Exception:
    pass

# Create collection
create_body = {
    "vectors": {
        "size": 128,
        "distance": "Cosine"
    },
    "hnsw_config": {
        "m": 16,
        "ef_construct": 100
    }
}

status, body, raw = safe_request("PUT", f"/collections/{COLL_NAME}", json=create_body)
print(f"Create collection status: {status}")
print(f"Create collection raw: {raw}")

if status != 200:
    print(f"VERDICT: SCRIPT_ERROR — Initial create failed with status {status}")
    sys.exit(2)

# Verify collection exists via get
status_get, body_get, raw_get = safe_request("GET", f"/collections/{COLL_NAME}")
print(f"Get collection status: {status_get}")
print(f"Get collection raw: {raw_get}")

if status_get != 200:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Collection not visible after creation (status {status_get})")
    sys.exit(1)

# Verify collection exists via list
status_list, body_list, raw_list = safe_request("GET", "/collections")
print(f"List collections status: {status_list}")
print(f"List collections raw: {raw_list}")

if status_list != 200:
    print(f"VERDICT: SCRIPT_ERROR — List collections failed with status {status_list}")
    sys.exit(2)

# Check if collection name appears in list
collection_names = []
try:
    collections = body_list.get("result", {}).get("collections", [])
    collection_names = [c.get("name") for c in collections if isinstance(c, dict)]
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR — Failed to parse list response: {e}")
    sys.exit(2)

print(f"Collection names in list: {collection_names}")

if COLL_NAME not in collection_names:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Collection not in list after creation")
    sys.exit(1)

# Test: Create same collection again - should get 400 Bad Request
status_dup, body_dup, raw_dup = safe_request("PUT", f"/collections/{COLL_NAME}", json=create_body)
print(f"Duplicate create status: {status_dup}")
print(f"Duplicate create raw: {raw_dup}")

if status_dup == 200:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Creating existing collection returned 200 (should be 400)")
    sys.exit(1)
elif status_dup == 400:
    print(f"VERDICT: NO_DEFECT — Duplicate create correctly returned 400 Bad Request")
else:
    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Duplicate create returned unexpected status {status_dup}")
    sys.exit(1)

# Cleanup
try:
    safe_request("DELETE", f"/collections/{COLL_NAME}")
except Exception:
    pass

sys.exit(0)
