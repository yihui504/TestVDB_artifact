"""
Attack: delete_consistency, count_visibility

Tests delete collection → count returns 0/404 (qdrant_invariant_delete_invisibility_001)
and search returns empty results.
"""
import os
import sys

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

COLL_NAME = "state_delete_test"

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

# Verify collection exists
status, _, raw = safe_request("GET", f"/collections/{COLL_NAME}")
print(f"Get collection before delete: {status}")
if status != 200:
    print(f"Unexpected status before delete: {raw}")
    print("VERDICT: SCRIPT_ERROR — Collection should exist")
    sys.exit(2)

# Delete collection
status, _, raw = safe_request("DELETE", f"/collections/{COLL_NAME}")
print(f"Delete collection: {status}")
if status not in [200, 204]:
    print(f"Delete failed: {raw}")
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Delete failed")
    sys.exit(1)

# Verify collection is gone (GET should return 404)
status, body, raw = safe_request("GET", f"/collections/{COLL_NAME}")
print(f"Get collection after delete: {status}")
if status == 404:
    print("Correct: GET returns 404 after delete")
elif status == 200:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Collection still visible after delete")
    sys.exit(1)
else:
    print(f"Unexpected status after delete: {raw}")
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Unexpected status after delete")
    sys.exit(1)

# Verify collection not in list
status, body, raw = safe_request("GET", "/collections")
print(f"List collections: {status}")
if status == 200:
    collections = body.get("result", {}).get("collections", []) if isinstance(body, dict) else []
    coll_names = [c.get("name", "") for c in collections]
    if COLL_NAME in coll_names:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Collection still in list after delete")
        sys.exit(1)
    else:
        print("Correct: Collection not in list after delete")
else:
    print(f"List endpoint failed: {raw}")
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — List endpoint failed")
    sys.exit(1)

# Verify count/search are inaccessible
status, _, raw = safe_request("POST", f"/collections/{COLL_NAME}/points/count", json={})
print(f"Count after delete: {status}")
if status != 404:
    print(f"Expected 404 for count after delete, got {status}")
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Count accessible after delete")
    sys.exit(1)

# Verify search is inaccessible
search_body = {
    "vector": [0.1] * 128,
    "limit": 10
}
status, _, raw = safe_request("POST", f"/collections/{COLL_NAME}/points/search", json=search_body)
print(f"Search after delete: {status}")
if status != 404:
    print(f"Expected 404 for search after delete, got {status}")
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Search accessible after delete")
    sys.exit(1)

print("VERDICT: NO_DEFECT")
