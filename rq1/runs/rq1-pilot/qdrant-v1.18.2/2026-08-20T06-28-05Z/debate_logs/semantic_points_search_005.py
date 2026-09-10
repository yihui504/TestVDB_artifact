#!/usr/bin/env python3
"""
semantic_points_search_005
Attack: behavioral_contract
Testing: points+search on empty collection returns empty array (no error)
Expected: Type4_StateLogicViolation if empty search doesn't return empty array
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
    """Create an empty test collection"""
    collection_name = "test_search_semantic_005"

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

    return collection_name

def cleanup_test_collection(collection_name):
    """Clean up test collection"""
    try:
        safe_request("DELETE", f"/collections/{collection_name}")
    except:
        pass

def test_search_empty_collection():
    """Test that search on empty collection returns empty array"""
    collection_name = setup_test_collection()

    try:
        search_payload = {
            "vector": [0.1] * 128,
            "limit": 10
        }

        SEARCH_PATH = f"/collections/{collection_name}/points/search"
        status, body, raw = safe_request("POST", SEARCH_PATH, json_data=search_payload)

        print(f"Status: {status}")
        print(f"Raw response: {raw[:500]}")

        if status != 200:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"Search on empty collection should return 200 OK, got {status}")
            sys.exit(1)

        if not isinstance(body, list):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"Search should return array, got {type(body)}")
            sys.exit(1)

        if len(body) != 0:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"Search on empty collection should return empty array, got {len(body)} results")
            sys.exit(1)

        print("VERDICT: NO_DEFECT")

    finally:
        cleanup_test_collection(collection_name)

if __name__ == "__main__":
    test_search_empty_collection()
