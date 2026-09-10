#!/usr/bin/env python3
"""
Attack: Type coercion in upsert payload - Type1 illegal success
Target: Verify API doesn't accept incorrect types for payload fields
Strategy: type_coercion
"""
import os, sys, json, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

def safe_request(method, endpoint, json=None, timeout=10):
    """Safe HTTP request wrapper returning (status, body, raw)"""
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(method, url, json=json, headers=headers, timeout=timeout)
        status = response.status_code
        raw = response.text
        try:
            body = response.json()
        except:
            body = raw
        return status, body, raw
    except Exception as e:
        return -1, str(e), str(e)

COLLECTION = "test_upsert_payload_types"
VECTOR_DIM = 128

def setup():
    """Create test collection"""
    try:
        safe_request("DELETE", f"/collections/{COLLECTION}")
    except:
        pass

    status, body, raw = safe_request("PUT", f"/collections/{COLLECTION}", json={
        "vectors": {
            "size": VECTOR_DIM,
            "distance": "Cosine"
        }
    })
    if status not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — setup failed: {status}")
        print(raw)
        sys.exit(2)

def teardown():
    """Cleanup test collection"""
    try:
        safe_request("DELETE", f"/collections/{COLLECTION}")
    except Exception:
        pass

def test_type_coercion_in_payload():
    """
    Test that API doesn't silently coerce types in payload.
    Point id should be integer/string, vector should be array of numbers.
    """
    setup()

    # Test 1: Point ID as float (should reject or coerce, not silently accept)
    print("\n--- Test 1: Point ID as float (1.5) ---")
    status, body, raw = safe_request("PUT", f"/collections/{COLLECTION}/points", json={
        "points": [{
            "id": 1.5,  # Float ID - should this be accepted?
            "vector": [0.1] * VECTOR_DIM,
            "payload": {"value": "test"}
        }]
    })
    print(raw)

    # If accepted, that's potential type coercion issue
    if status == 200:
        print("WARNING: Float ID accepted - may indicate type coercion")

    # Test 2: Vector with string values (should reject)
    print("\n--- Test 2: Vector with string values ---")
    status, body, raw = safe_request("PUT", f"/collections/{COLLECTION}/points", json={
        "points": [{
            "id": 2,
            "vector": ["0.1"] * VECTOR_DIM,  # Strings instead of floats
            "payload": {"value": "test"}
        }]
    })
    print(raw)

    if status == 200:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)")
        print("Vector with string values should be rejected but was accepted")
        teardown()
        sys.exit(1)

    # Test 3: Payload with nested invalid types (array instead of object)
    print("\n--- Test 3: Payload as array instead of object ---")
    status, body, raw = safe_request("PUT", f"/collections/{COLLECTION}/points", json={
        "points": [{
            "id": 3,
            "vector": [0.1] * VECTOR_DIM,
            "payload": ["tag1", "tag2"]  # Array instead of object
        }]
    })
    print(raw)

    # This might be valid (array payload), so just log, don't fail
    if status != 200:
        print("NOTE: Array payload rejected (may be by design)")

    # Test 4: Negative limit in search (different endpoint, related coercion)
    print("\n--- Test 4: String 'limit' parameter in search ---")
    status, body, raw = safe_request("POST", f"/collections/{COLLECTION}/points/search", json={
        "vector": [0.1] * VECTOR_DIM,
        "limit": "10"  # String instead of integer
    })
    print(raw)

    if status == 200:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)")
        print("String '10' for limit should be rejected but was accepted")
        teardown()
        sys.exit(1)

    print("\nVERDICT: NO_DEFECT")
    teardown()

if __name__ == "__main__":
    test_type_coercion_in_payload()
