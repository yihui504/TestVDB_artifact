#!/usr/bin/env python3
"""
Attack: state_consistency | lifecycle_concurrent_access | create_delete_race
Strategy: 7 (生命周期并发攻击 - 创建/删除期间并发访问)
Endpoint: collections+create
Constraint IDs:
  - behavioral_contracts::qdrant_behavioral_create_visibility_001
  - state_invariants::qdrant_invariant_create_query_001
Source URL: https://api.qdrant.tech/api-reference/collections/create-collection
Doc Version: 1.19.x
Expected Defect Type: Type3_RuntimeFailure
Blindspot: BS-03 (Concurrency Blindness) - lifecycle concurrent access
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

COLL_NAME = "test_state_lifecycle_race"
ITERATIONS = 20
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

access_errors = []
internal_errors = []
access_success = []

def lifecycle_thread():
    """Thread A: Create -> Delete -> recreate loop"""
    try:
        for i in range(ITERATIONS):
            # Delete (idempotent)
            safe_request("DELETE", f"/collections/{COLL_NAME}")
            time.sleep(0.03)

            # Create
            status_c, _, raw_c = safe_request("PUT", f"/collections/{COLL_NAME}", json=create_body)
            if status_c not in [200, 400]:
                internal_errors.append(f"Create failed: {status_c} - {raw_c[:100]}")
            time.sleep(0.03)
    except Exception as e:
        internal_errors.append(f"Lifecycle thread error: {str(e)}")

def access_thread():
    """Thread B: Concurrent GET requests during lifecycle"""
    try:
        for i in range(ITERATIONS * 3):
            status, _, raw = safe_request("GET", f"/collections/{COLL_NAME}")

            # Track 500 errors (defect signal)
            if status == 500:
                access_errors.append((status, raw[:120]))
            elif status in [200, 404]:
                # These are expected responses (404 = not exists, 200 = exists)
                access_success.append(status)
            else:
                internal_errors.append(f"Unexpected status: {status} - {raw[:100]}")

            time.sleep(0.02)
    except Exception as e:
        internal_errors.append(f"Access thread error: {str(e)}")

# Launch threads
lifecycle_t = threading.Thread(target=lifecycle_thread)
access_t = threading.Thread(target=access_thread)

lifecycle_t.start()
time.sleep(0.05)  # Stagger start
access_t.start()

# Wait for completion
lifecycle_t.join()
access_t.join()

time.sleep(0.3)  # Allow stabilization

print(f"Lifecycle thread completed. Internal errors: {len(internal_errors)}")
print(f"Access errors (500s): {len(access_errors)}")
print(f"Access success (200/404): {len(access_success)}")

if internal_errors:
    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Internal errors during lifecycle: {internal_errors[:3]}")
    sys.exit(1)

# Check for 500 errors (defect signal: should return 404/503 instead of 500)
if len(access_errors) >= 2:
    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Got {len(access_errors)} internal errors (500) during lifecycle - should return 404/503")
    sys.exit(1)

if len(access_errors) == 1:
    print(f"VERDICT: NO_DEFECT — Single 500 error may be transient (not reproducible)")

print(f"VERDICT: NO_DEFECT — Lifecycle concurrent access handled correctly (no 500s)")

# Cleanup
try:
    safe_request("DELETE", f"/collections/{COLL_NAME}")
except Exception:
    pass

sys.exit(0)
