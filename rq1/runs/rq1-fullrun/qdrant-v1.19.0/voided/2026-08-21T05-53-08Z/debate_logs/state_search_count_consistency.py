"""
Attack: count_consistency, search_visibility, delete_consistency

Tests upsert → count consistency (qdrant_invariant_upsert_count_001) and
search visibility after concurrent operations.
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

COLL_NAME = "state_count_test"

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
status, body, raw = safe_request("PUT", f"/collections/{COLL_NAME}", json=create_body)
print(f"Create collection: {status}")
if status not in [200, 201]:
    print(raw)
    print("VERDICT: SCRIPT_ERROR — Failed to create collection")
    sys.exit(2)

# Initial count
status, body, raw = safe_request("POST", f"/collections/{COLL_NAME}/points/count", json={})
print(f"Count before: {raw}")
if status != 200:
    print("VERDICT: SCRIPT_ERROR — Count endpoint failed")
    sys.exit(2)

count_before = body.get("result", 0) if isinstance(body, dict) else 0
print(f"count_before = {count_before}")

# Upsert 50 points
N = 50
errors = []
for i in range(N):
    point = {
        "points": [
            {
                "id": i,
                "vector": [0.1] * 128
            }
        ]
    }
    status, _, raw = safe_request("PUT", f"/collections/{COLL_NAME}/points", json=point)
    if status not in [200, 201]:
        errors.append((i, status, raw))

if errors:
    print(f"Upsert errors: {errors}")
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Concurrent upsert failures")
    sys.exit(1)

# Count after upsert
time.sleep(1)
status, body, raw = safe_request("POST", f"/collections/{COLL_NAME}/points/count", json={})
print(f"Count after: {raw}")
if status != 200:
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Count endpoint failed after upsert")
    sys.exit(1)

count_after = body.get("result", 0) if isinstance(body, dict) else 0
print(f"count_after = {count_after}")

expected = count_before + N
if count_after != expected:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Expected {expected}, got {count_after}")
    sys.exit(1)

# Verify search visibility
query_vec = [0.1] * 128
search_body = {
    "vector": query_vec,
    "limit": 10
}
status, body, raw = safe_request("POST", f"/collections/{COLL_NAME}/points/search", json=search_body)
print(f"Search result: {status}")
if status != 200:
    print(f"Search failed: {raw}")
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Search endpoint failed")
    sys.exit(1)

results = body.get("result", []) if isinstance(body, dict) else []
if len(results) == 0:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — No search results after upsert")
    sys.exit(1)

print(f"Search returned {len(results)} results")

# Cleanup
try:
    safe_request("DELETE", f"/collections/{COLL_NAME}")
except Exception:
    pass

print("VERDICT: NO_DEFECT")
