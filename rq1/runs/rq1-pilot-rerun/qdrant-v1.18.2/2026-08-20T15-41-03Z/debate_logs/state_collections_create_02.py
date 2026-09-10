#!/usr/bin/env python3
"""
Attack: qdrant_state_create_collection_001 (constraints::qdrant_state_create_collection_001)
Testing: Collection creation is atomic - fails if collection already exists
Strategy: atomicity
Endpoint: collections+create
Constraint IDs: [constraints::qdrant_state_create_collection_001]
Source URL: https://api.qdrant.tech/api-reference/collections/create-collection
Doc Version: 1.19.x
Expected Defect Type: Type4_StateLogicViolation
"""

import os
import sys

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

COLLECTION_NAME = "test_state_atomic_001_cleanup"

# Cleanup: delete collection if exists
try:
    safe_request("DELETE", f"/collections/{COLLECTION_NAME}")
except Exception:
    pass

# Create collection first time
create_body = {
    "vectors": {
        "size": 64,
        "distance": "Euclidean"
    }
}

status, body, raw = safe_request("PUT", f"/collections/{COLLECTION_NAME}", json=create_body)
print(f"First create status: {status}, raw: {raw[:200]}")

if status != 200:
    print(f"VERDICT: SCRIPT_ERROR — Initial create failed with status {status}")
    sys.exit(2)

# Try to create same collection again - should fail
status, body, raw = safe_request("PUT", f"/collections/{COLLECTION_NAME}", json=create_body)
print(f"Duplicate create status: {status}, raw: {raw[:500]}")

# Expected: 400 Bad Request or similar (not 200)
if status == 200:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Duplicate collection creation succeeded (should fail)")
    # Cleanup before exit
    try:
        safe_request("DELETE", f"/collections/{COLLECTION_NAME}")
    except Exception:
        pass
    sys.exit(1)

# Verify it's a proper error (not 500)
if status == 500:
    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Duplicate create returned 500 instead of proper error")
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
