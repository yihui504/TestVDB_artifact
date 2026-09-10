"""
Attack: lifecycle_concurrent (策略 7 - 生命周期并发攻击)

Tests concurrent collection lifecycle (create/delete/recreate) with access operations (query/search).
Detects 500 internal errors when accessing a collection during lifecycle transitions.
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

COLL_NAME = "state_lifecycle_test"

# Cleanup
try:
    safe_request("DELETE", f"/collections/{COLL_NAME}")
except Exception:
    pass

def lifecycle_thread():
    """Thread A: create → delete → recreate cycle."""
    for i in range(3):
        # Create
        create_body = {
            "vectors": {
                "size": 128,
                "distance": "Cosine"
            }
        }
        status, _, raw = safe_request("PUT", f"/collections/{COLL_NAME}", json=create_body)
        print(f"[Lifecycle] Create iteration {i}: {status}")
        time.sleep(0.05)

        # Delete
        status, _, raw = safe_request("DELETE", f"/collections/{COLL_NAME}")
        print(f"[Lifecycle] Delete iteration {i}: {status}")
        time.sleep(0.05)

def access_thread():
    """Thread B: concurrent access (query, search, count)."""
    errors = []
    for i in range(20):
        # Mix of operations
        ops = [
            ("GET", f"/collections/{COLL_NAME}"),
            ("POST", f"/collections/{COLL_NAME}/points/count", {}),
            ("POST", f"/collections/{COLL_NAME}/points/search", {"vector": [0.1] * 128, "limit": 5})
        ]

        for method, endpoint, *args in ops:
            json_body = args[0] if args else None
            status, _, raw = safe_request(method, endpoint, json=json_body)

            # 500 is defect (should be 404 or 503)
            if status == 500:
                errors.append((method, endpoint, status, raw[:120]))
            # 404 is acceptable (collection temporarily doesn't exist)
            # 200/201 is acceptable (operation succeeded)
            # 503 is acceptable (service temporarily unavailable)

        time.sleep(0.03)

    return errors

# Launch threads
lifecycle_t = threading.Thread(target=lifecycle_thread)
access_t = threading.Thread(target=access_thread)

lifecycle_t.start()
access_t.start()

lifecycle_t.join()
access_errors = access_t.join()

print(f"\nAccess errors: {len(access_errors)}")
if access_errors:
    print(f"Error samples: {access_errors[:3]}")

# Filter for 500 errors
five_hundred_errors = [e for e in access_errors if e[2] == 500]
if five_hundred_errors:
    print(f"500 errors: {len(five_hundred_errors)}")
    print(f"Samples: {five_hundred_errors[:3]}")
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — 500 errors during lifecycle transitions")
    sys.exit(1)
elif access_errors:
    # Other non-500 errors are less severe
    print(f"Non-500 errors: {len(access_errors)}")
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Non-500 errors during lifecycle transitions")
    sys.exit(1)

# Cleanup
try:
    safe_request("DELETE", f"/collections/{COLL_NAME}")
except Exception:
    pass

print("VERDICT: NO_DEFECT")
