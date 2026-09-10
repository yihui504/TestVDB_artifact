#!/usr/bin/env python3
"""
Attack: qdrant_behavioral_search_points_002 - Empty collection behavior
Target: Search on empty collection should return empty results, not error
Strategy: behavioral_contract
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

COLLECTION = "test_search_empty"
VECTOR_DIM = 128

def setup():
    """Create empty test collection"""
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

def test_search_empty_collection():
    """
    Test search on empty collection.
    Contract qdrant_behavioral_search_points_002: returns 200 OK with empty array, no error
    """
    setup()

    # Search empty collection
    status, body, raw = safe_request("POST", f"/collections/{COLLECTION}/points/search", json={
        "vector": [0.1] * VECTOR_DIM,
        "limit": 10
    })

    print(raw)

    if status != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure)")
        print(f"Empty collection search should return 200, got {status}")
        teardown()
        sys.exit(1)

    # Extract results from Qdrant response
    results = body.get("result") if isinstance(body, dict) else None

    if results is None:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"Expected results array in response, got: {body}")
        teardown()
        sys.exit(1)

    if not hasattr(results, '__len__'):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"Expected array, got: {type(results)}")
        teardown()
        sys.exit(1)

    if len(results) != 0:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"Empty collection search should return 0 results, got {len(results)}")
        teardown()
        sys.exit(1)

    print("VERDICT: NO_DEFECT")
    teardown()

if __name__ == "__main__":
    test_search_empty_collection()
