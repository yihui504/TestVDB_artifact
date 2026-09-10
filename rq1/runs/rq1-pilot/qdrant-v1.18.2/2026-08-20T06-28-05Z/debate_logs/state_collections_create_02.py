#!/usr/bin/env python3
"""
Attack: state_consistency | concurrent_create | race_condition
Strategy: 4 (并发操作攻击 - 并发创建同名集合)
Endpoint: collections+create
Constraint IDs:
  - assertions::qdrant_behavioral_create_collection_002
  - state_constraints::qdrant_state_create_collection_001
Source URL: https://api.qdrant.tech/api-reference/collections/create-collection
Doc Version: 1.19.x
Expected Defect Type: Type4_StateLogicViolation
Blindspot: BS-03 (Concurrency Blindness) - concurrent creation race
"""

import os
import sys
import time
import threading
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

COLL_NAME = "test_state_concurrent_create"
THREAD_COUNT = 10
create_body = {
    "vectors": {
        "size": 128,
        "distance": "Cosine"
    }
}

# Cleanup: try delete existing collection
try:
    safe_request("DELETE", f"/collections/{COLL_NAME}")
    time.sleep(0.2)
except Exception:
    pass

results = []
errors = []

def create_collection(thread_id):
    """Thread function to create collection concurrently"""
    try:
        status, body, raw = safe_request("PUT", f"/collections/{COLL_NAME}", json=create_body)
        results.append((thread_id, status, raw))

        if status not in [200, 400]:
            errors.append(f"Thread {thread_id}: unexpected status {status}")
    except Exception as e:
        errors.append(f"Thread {thread_id}: {str(e)}")

# Launch concurrent create requests
threads = []
for i in range(THREAD_COUNT):
    t = threading.Thread(target=create_collection, args=(i,))
    threads.append(t)
    t.start()

# Wait for all threads
for t in threads:
    t.join()

time.sleep(0.5)  # Allow eventual consistency

print(f"Concurrent create results: {len(results)} requests")
print(f"Status codes: {[r[1] for r in results]}")

if errors:
    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Concurrent create errors: {errors}")
    sys.exit(1)

# Count successes and failures
success_count = sum(1 for r in results if r[1] == 200)
bad_request_count = sum(1 for r in results if r[1] == 400)
other_count = len(results) - success_count - bad_request_count

print(f"Success count (200): {success_count}")
print(f"Bad request count (400): {bad_request_count}")
print(f"Other status count: {other_count}")

# Expected: exactly 1 success (first create), all others should be 400 (already exists)
if success_count > 1:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Multiple successful creates ({success_count}) - collection creation not atomic")
    sys.exit(1)

if success_count == 0:
    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — No successful creates - all failed")
    sys.exit(1)

if bad_request_count != THREAD_COUNT - 1:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Expected {THREAD_COUNT-1} 400s, got {bad_request_count}")
    sys.exit(1)

# Verify final state: collection should exist
status_get, body_get, raw_get = safe_request("GET", f"/collections/{COLL_NAME}")
print(f"Final get collection status: {status_get}")

if status_get != 200:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Collection not visible after concurrent creates")
    sys.exit(1)

print(f"VERDICT: NO_DEFECT — Concurrent creation handled correctly (1 success, {THREAD_COUNT-1} 400s)")

# Cleanup
try:
    safe_request("DELETE", f"/collections/{COLL_NAME}")
except Exception:
    pass

sys.exit(0)
