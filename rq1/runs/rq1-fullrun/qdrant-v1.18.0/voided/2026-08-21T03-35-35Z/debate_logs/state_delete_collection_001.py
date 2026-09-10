#!/usr/bin/env python3
"""
Attack: state_consistency
Strategy: delete_consistency
Endpoint: /collections/{collection_name}:DELETE
Constraint: qdrant_state_delete_collection_001
Expected: Type4_StateLogicViolation

Tests delete atomicity - deleted collection should not exist and all data removed.
Validates state_invariant: qdrant_invariant_delete_not_exists_001
"""
import os
import sys
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

COLL_NAME = "test_state_delete_001"
VECTOR_DIM = 128

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

def cleanup():
    """Remove test collection if exists."""
    try:
        safe_request("DELETE", f"/collections/{COLL_NAME}")
    except Exception:
        pass

def setup_collection_with_data():
    """Create collection and add data."""
    create_body = {
        "vectors": {
            "size": VECTOR_DIM,
            "distance": "Cosine"
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{COLL_NAME}", json=create_body)
    print(f"Create collection: status={status}, raw={raw[:200]}")
    if status not in [200, 201]:
        print(f"VERDICT: SCRIPT_ERROR — Failed to create collection")
        sys.exit(2)

    # Add some points
    points = [{"id": i, "vector": [0.1] * VECTOR_DIM} for i in range(5)]
    upsert_body = {"points": points, "wait": True}
    status, body, raw = safe_request("PUT", f"/collections/{COLL_NAME}/points", json=upsert_body)
    print(f"Upsert points: status={status}")
    if status not in [200, 201]:
        print(f"VERDICT: SCRIPT_ERROR — Failed to upsert points")
        sys.exit(2)

def delete_collection():
    """Delete the collection."""
    status, body, raw = safe_request("DELETE", f"/collections/{COLL_NAME}")
    print(f"Delete collection: status={status}, raw={raw[:200]}")
    return status

def get_collection():
    """Get collection info."""
    status, body, raw = safe_request("GET", f"/collections/{COLL_NAME}")
    print(f"Get collection: status={status}, raw={raw[:200]}")
    return status, body

def main():
    cleanup()  # Ensure clean state
    setup_collection_with_data()

    # Delete the collection
    delete_status = delete_collection()
    if delete_status not in [200, 204]:
        print(f"VERDICT: SCRIPT_ERROR — Delete failed with status {delete_status}")
        cleanup()
        sys.exit(2)

    # Verify collection no longer exists (should be 404)
    get_status, get_body = get_collection()

    if get_status == 404:
        print(f"VERDICT: NO_DEFECT — Collection correctly removed after delete (404)")
        cleanup()
        sys.exit(0)
    elif get_status == 200:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Collection still exists after delete")
        print(f"  State invariant violation: AFTER delete(collection) EXISTS(collection) should be false")
        print(f"  Get returned 200 OK when it should return 404 Not Found")
        cleanup()
        sys.exit(1)
    else:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Unexpected status after delete: {get_status}")
        print(f"  Expected 404 Not Found, got {get_status}")
        cleanup()
        sys.exit(1)

if __name__ == "__main__":
    main()
