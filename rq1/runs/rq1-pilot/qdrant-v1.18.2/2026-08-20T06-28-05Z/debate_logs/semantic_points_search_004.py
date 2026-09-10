#!/usr/bin/env python3
"""
semantic_points_search_004
Attack: type_coercion
Testing: points+search rejects incorrect limit types (string, float, boolean)
Expected: Type1_IllegalSuccess if incorrect types are accepted
Blindspot: BS-05 Documentation Drift
"""

import os, sys, json, time

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

import requests

def safe_request(method, endpoint, json_data=None, params=None):
    """Safe request wrapper returning (status, body, raw)"""
    url = f"{BASE_URL}{endpoint}"
    try:
        if method.upper() == "GET":
            resp = requests.get(url, params=params, timeout=10)
        elif method.upper() == "POST":
            resp = requests.post(url, json=json_data, params=params, timeout=10)
        elif method.upper() == "PUT":
            resp = requests.put(url, json=json_data, timeout=10)
        elif method.upper() == "DELETE":
            resp = requests.delete(url, json=json_data, params=params, timeout=10)
        else:
            return 0, {}, f"Unsupported method: {method}"

        raw_text = resp.text
        try:
            body = resp.json()
        except:
            body = {"raw": raw_text}

        return resp.status_code, body, raw_text
    except Exception as e:
        return 0, {}, f"Request failed: {str(e)}"

def setup_test_collection():
    """Create a test collection"""
    collection_name = "test_search_semantic_004"

    create_payload = {
        "vectors": {
            "size": 128,
            "distance": "Cosine"
        }
    }

    status, _, raw = safe_request("PUT", f"/collections/{collection_name}", json_data=create_payload)
    if status not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — failed to create collection: {status}")
        sys.exit(2)

    # Insert test points
    points = [{"id": 1, "vector": [0.1] * 128}]
    status, _, raw = safe_request("PUT", f"/collections/{collection_name}/points", json_data={"points": points})
    if status not in (200, 201, 204):
        print(f"VERDICT: SCRIPT_ERROR — failed to insert points: {status}")
        sys.exit(2)

    return collection_name

def cleanup_test_collection(collection_name):
    """Clean up test collection"""
    try:
        safe_request("DELETE", f"/collections/{collection_name}")
    except:
        pass

def test_search_limit_type_coercion():
    """Test that search rejects incorrect limit types"""
    collection_name = setup_test_collection()

    try:
        # Test incorrect types for limit parameter
        test_cases = [
            ("string '100'", {"vector": [0.1] * 128, "limit": "100"}),
            ("float 5.0", {"vector": [0.1] * 128, "limit": 5.0}),
            ("boolean true", {"vector": [0.1] * 128, "limit": True}),
            ("null", {"vector": [0.1] * 128, "limit": None}),
        ]

        for desc, search_payload in test_cases:
            SEARCH_PATH = f"/collections/{collection_name}/points/search"
            status, body, raw = safe_request("POST", SEARCH_PATH, json_data=search_payload)

            print(f"Testing {desc}: status={status}")

            # If accepted (200 OK), that's a defect
            if status == 200:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)")
                print(f"Incorrect limit type ({desc}) was accepted")
                print(f"API should reject non-integer limit values")
                sys.exit(1)

        print("VERDICT: NO_DEFECT")

    finally:
        cleanup_test_collection(collection_name)

if __name__ == "__main__":
    test_search_limit_type_coercion()
