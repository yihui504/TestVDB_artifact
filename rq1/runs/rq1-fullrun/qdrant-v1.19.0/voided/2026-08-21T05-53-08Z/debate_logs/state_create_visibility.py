"""
Attack: create_visibility (qdrant_invariant_create_visibility_001)

Tests that created collection is immediately visible and queryable.
"""
import os
import sys
import time

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

COLL_NAME = "state_visibility_test"

# Cleanup
try:
    safe_request("DELETE", f"/collections/{COLL_NAME}")
except Exception:
    pass

# Verify collection doesn't exist
status, _, raw = safe_request("GET", f"/collections/{COLL_NAME}")
print(f"Get before create: {status}")
if status == 200:
    print("VERDICT: SCRIPT_ERROR — Collection should not exist before create")
    sys.exit(2)

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
    print(f"Create failed: {raw}")
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Create collection failed")
    sys.exit(1)

# Verify collection is visible via GET
status, body, raw = safe_request("GET", f"/collections/{COLL_NAME}")
print(f"Get after create: {status}")
if status != 200:
    print(f"Collection not visible: {raw}")
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Collection not visible after create")
    sys.exit(1)

# Verify collection details
if isinstance(body, dict):
    result = body.get("result", {})
    config = result.get("config", {}).get("params", {}).get("vectors", {})
    size = config.get("size", 0)
    distance = config.get("distance", "")
    print(f"Collection config: size={size}, distance={distance}")
    if size != 128 or distance != "Cosine":
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Config mismatch. Expected size=128, distance=Cosine")
        sys.exit(1)
else:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Invalid response structure")
    sys.exit(1)

# Verify collection appears in list
status, body, raw = safe_request("GET", "/collections")
print(f"List collections: {status}")
if status != 200:
    print(f"List failed: {raw}")
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — List collections failed")
    sys.exit(1)

collections = body.get("result", {}).get("collections", []) if isinstance(body, dict) else []
coll_names = [c.get("name", "") for c in collections]
print(f"Collections in list: {coll_names}")

if COLL_NAME not in coll_names:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Collection not in list after create")
    sys.exit(1)

# Verify collection is immediately queryable (upsert + search)
point = {
    "points": [
        {
            "id": 1,
            "vector": [0.1] * 128
        }
    ]
}
status, _, raw = safe_request("PUT", f"/collections/{COLL_NAME}/points", json=point)
print(f"Upsert point: {status}")
if status not in [200, 201]:
    print(f"Upsert failed: {raw}")
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Upsert failed on new collection")
    sys.exit(1)

time.sleep(0.5)

search_body = {
    "vector": [0.1] * 128,
    "limit": 10
}
status, body, raw = safe_request("POST", f"/collections/{COLL_NAME}/points/search", json=search_body)
print(f"Search: {status}")
if status != 200:
    print(f"Search failed: {raw}")
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Search failed on new collection")
    sys.exit(1)

results = body.get("result", []) if isinstance(body, dict) else []
if len(results) == 0:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — No search results after upsert on new collection")
    sys.exit(1)

# Verify count endpoint works
status, body, raw = safe_request("POST", f"/collections/{COLL_NAME}/points/count", json={})
print(f"Count: {status}")
if status != 200:
    print(f"Count failed: {raw}")
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Count failed on new collection")
    sys.exit(1)

count = body.get("result", 0) if isinstance(body, dict) else 0
print(f"Count result: {count}")
if count != 1:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Count mismatch after upsert. Expected 1, got {count}")
    sys.exit(1)

# Cleanup
try:
    safe_request("DELETE", f"/collections/{COLL_NAME}")
except Exception:
    pass

print("VERDICT: NO_DEFECT")
