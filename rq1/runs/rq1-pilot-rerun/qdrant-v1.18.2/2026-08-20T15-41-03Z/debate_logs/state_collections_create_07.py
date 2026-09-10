#!/usr/bin/env python3
"""
Attack: Concurrent collection lifecycle with access operations (Strategy 7)
Testing: Collection create/delete lifecycle should not cause 500 errors during concurrent access
Strategy: concurrent_lifecycle
Endpoint: collections+create
Constraint IDs: [constraints::qdrant_state_create_collection_001, constraints::qdrant_state_delete_collection_001]
Source URL: https://api.qdrant.tech/api-reference/collections/create-collection
Doc Version: 1.19.x
Expected Defect Type: Type3_RuntimeFailure
"""

import os
import sys
import threading
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

COLLECTION_NAME = "test_concurrent_lifecycle_cleanup"
ITERATIONS = 10

# Cleanup initial
try:
    safe_request("DELETE", f"/collections/{COLLECTION_NAME}")
except Exception:
    pass

errors_access = []
errors_lifecycle = []

def lifecycle_thread():
    """Thread that creates and deletes collection repeatedly"""
    for i in range(ITERATIONS):
        # Create
        create_body = {
            "vectors": {
                "size": 32,
                "distance": "Cosine"
            }
        }
        status, body, raw = safe_request("PUT", f"/collections/{COLLECTION_NAME}", json=create_body)
        if status == 500:
            errors_lifecycle.append(f"create_500_iter_{i}")

        time.sleep(0.02)

        # Delete
        status, body, raw = safe_request("DELETE", f"/collections/{COLLECTION_NAME}")
        if status == 500:
            errors_lifecycle.append(f"delete_500_iter_{i}")

        time.sleep(0.02)

def access_thread():
    """Thread that performs concurrent access operations (query/get)"""
    for i in range(ITERATIONS * 2):
        # Try to get collection (may or may not exist)
        status, body, raw = safe_request("GET", f"/collections/{COLLECTION_NAME}")

        # 500 is defect (should be 200 or 404)
        if status == 500:
            errors_access.append(f"get_500_iter_{i}")

        time.sleep(0.015)

# Start threads
t1 = threading.Thread(target=lifecycle_thread)
t2 = threading.Thread(target=access_thread)

t1.start()
t2.start()

t1.join()
t2.join()

print(f"Lifecycle errors: {errors_lifecycle}")
print(f"Access errors: {errors_access}")

# Cleanup final
try:
    safe_request("DELETE", f"/collections/{COLLECTION_NAME}")
except Exception:
    pass

if errors_access or errors_lifecycle:
    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Concurrent lifecycle operations caused 500 errors")
    sys.exit(1)

print("VERDICT: NO_DEFECT")
sys.exit(0)
