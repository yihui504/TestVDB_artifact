#!/usr/bin/env python3
"""
Attack: state_consistency | high_concurrency_create | thread_safety
Strategy: 4 (并发操作攻击 - 高并发创建不同集合)
Endpoint: collections+create
Constraint IDs:
  - state_constraints::qdrant_state_create_collection_001
  - state_constraints::qdrant_state_upsert_points_001
Source URL: https://api.qdrant.tech/api-reference/collections/create-collection
Doc Version: 1.19.x
Expected Defect Type: Type3_RuntimeFailure
Blindspot: BS-03 (Concurrency Blindness) - high concurrency thread safety
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

THREAD_COUNT = 20
COLL_PREFIX = "test_state_high_concurrency_"

results = []
errors = []
lock = threading.Lock()

def create_collection_thread(thread_id):
    """Thread to create a unique collection"""
    coll_name = f"{COLL_PREFIX}{thread_id:03d}"
    create_body = {
        "vectors": {
            "size": 128,
            "distance": "Cosine"
        }
    }

    try:
        status, body, raw = safe_request("PUT", f"/collections/{coll_name}", json=create_body)

        with lock:
            results.append((thread_id, coll_name, status, raw))

        if status not in [200, 400]:
            errors.append(f"Thread {thread_id}: unexpected status {status} - {raw[:80]}")

    except Exception as e:
        with lock:
            errors.append(f"Thread {thread_id}: exception {str(e)}")

# Launch threads
threads = []
for i in range(THREAD_COUNT):
    t = threading.Thread(target=create_collection_thread, args=(i,))
    threads.append(t)
    t.start()

# Wait for completion
for t in threads:
    t.join()

time.sleep(0.5)  # Allow eventual consistency

print(f"High concurrency test completed: {len(results)} requests")
print(f"Errors: {len(errors)}")

if errors:
    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — High concurrency errors:")
    for err in errors[:3]:
        print(f"  - {err}")
    sys.exit(1)

# Count successes
successes = sum(1 for r in results if r[2] == 200)
print(f"Successful creates: {successes}/{THREAD_COUNT}")

# Verify all collections exist
missing = []
for r in results:
    if r[2] == 200:
        coll_name = r[1]
        status_g, _, raw_g = safe_request("GET", f"/collections/{coll_name}")
        if status_g != 200:
            missing.append(f"{coll_name} (create returned 200, but get returned {status_g})")

if missing:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Collections not visible after concurrent create:")
    for m in missing[:3]:
        print(f"  - {m}")
    sys.exit(1)

# Verify in list
status_list, body_list, raw_list = safe_request("GET", "/collections")
if status_list == 200:
    try:
        collections = body_list.get("result", {}).get("collections", [])
        existing_names = {c.get("name") for c in collections if isinstance(c, dict)}

        for r in results:
            if r[2] == 200:
                if r[1] not in existing_names:
                    errors.append(f"{r[1]} not in list despite successful create")
    except Exception as e:
        errors.append(f"Failed to parse list: {e}")

if errors:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — List visibility errors:")
    for err in errors[:3]:
        print(f"  - {err}")
    sys.exit(1)

print(f"VERDICT: NO_DEFECT — High concurrency create handled correctly ({successes}/{THREAD_COUNT} collections)")

# Cleanup all collections
for r in results:
    if r[2] == 200:
        try:
            safe_request("DELETE", f"/collections/{r[1]}")
        except Exception:
            pass

sys.exit(0)
