"""
Attack: concurrent (策略 4 - 并发操作攻击)

Tests concurrent upserts while searching (BS-03 Concurrency Blindness).
"""
import os
import sys
import time
import threading

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

import requests

def safe_request(method, endpoint, json=None, timeout=10):
    """Safe HTTP request wrapper with unified error handling."""
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

COLL_NAME = "state_concurrent_test"

# Cleanup
try:
    safe_request("DELETE", f"/collections/{COLL_NAME}")
except Exception:
    pass

# Create collection
create_body = {
    "vectors": {
        "size": 128,
        "distance": "Cosine"
    }
}
status, _, raw = safe_request("PUT", f"/collections/{COLL_NAME}", json=create_body)
print(f"Create collection: {status}")
if status not in [200, 201]:
    print(raw)
    print("VERDICT: SCRIPT_ERROR — Failed to create collection")
    sys.exit(2)

THREAD_COUNT = 10
POINTS_PER_THREAD = 10
errors = []
search_errors = []

def upsert_batch(thread_id):
    """Thread function: upsert points."""
    for i in range(POINTS_PER_THREAD):
        point_id = thread_id * POINTS_PER_THREAD + i
        point = {
            "points": [
                {
                    "id": point_id,
                    "vector": [0.1 * (point_id % 10)] * 128
                }
            ]
        }
        status, _, raw = safe_request("PUT", f"/collections/{COLL_NAME}/points", json=point)
        if status not in [200, 201]:
            errors.append((thread_id, point_id, status, raw[:120]))

def search_batch(thread_id):
    """Thread function: search while upserts happen."""
    for i in range(5):
        search_body = {
            "vector": [0.1] * 128,
            "limit": 10
        }
        status, body, raw = safe_request("POST", f"/collections/{COLL_NAME}/points/search", json=search_body)
        if status == 500:
            search_errors.append((thread_id, i, status, raw[:120]))
        elif status not in [200, 404]:
            search_errors.append((thread_id, i, status, raw[:120]))
        time.sleep(0.01)

# Launch threads
threads = []
for i in range(THREAD_COUNT):
    t1 = threading.Thread(target=upsert_batch, args=(i,))
    t2 = threading.Thread(target=search_batch, args=(i,))
    threads.extend([t1, t2])
    t1.start()
    t2.start()

# Wait for completion
for t in threads:
    t.join()

print(f"Upsert errors: {len(errors)}")
print(f"Search errors: {len(search_errors)}")

if errors:
    print(f"Upsert errors details: {errors[:3]}")
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Concurrent upsert failures")
    sys.exit(1)

if search_errors:
    print(f"Search errors details: {search_errors[:3]}")
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Search failed during concurrent upserts")
    sys.exit(1)

# Verify final count
time.sleep(1)
status, body, raw = safe_request("POST", f"/collections/{COLL_NAME}/points/count", json={})
print(f"Final count: {raw}")
if status != 200:
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Count endpoint failed after concurrent ops")
    sys.exit(1)

count = body.get("result", 0) if isinstance(body, dict) else 0
expected = THREAD_COUNT * POINTS_PER_THREAD
print(f"Expected: {expected}, Got: {count}")

if count != expected:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Count mismatch after concurrent ops")
    sys.exit(1)

# Cleanup
try:
    safe_request("DELETE", f"/collections/{COLL_NAME}")
except Exception:
    pass

print("VERDICT: NO_DEFECT")
