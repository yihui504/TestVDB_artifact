"""
Test: Type Coercion - HNSW Config Parameters
Attack: Type Confusion (Type-1)
Tests implicit type conversion for HNSW config numeric parameters
"""
import os
import sys
import json
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

def safe_request(method, endpoint, json_data=None, timeout=10):
    """Safe HTTP request wrapper with unified error handling."""
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.request(
            method=method,
            url=url,
            json=json_data,
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

def test_type_coercion_hnsw_config():
    """Test that HNSW config parameters don't accept incorrect types"""
    collection_base = "test_hnsw_type"

    # Test cases: HNSW params should be integers, not strings/floats/bools
    test_cases = [
        {
            "name": "m_as_string",
            "payload": {
                "vectors": {"size": 128, "distance": "Cosine"},
                "hnsw_config": {"m": "16"}
            },
            "should_accept": False,
            "desc": "String '16' instead of integer 16 for m"
        },
        {
            "name": "m_as_float",
            "payload": {
                "vectors": {"size": 128, "distance": "Cosine"},
                "hnsw_config": {"m": 16.5}
            },
            "should_accept": False,
            "desc": "Float 16.5 instead of integer 16 for m"
        },
        {
            "name": "m_as_bool",
            "payload": {
                "vectors": {"size": 128, "distance": "Cosine"},
                "hnsw_config": {"m": True}
            },
            "should_accept": False,
            "desc": "Boolean true instead of integer for m"
        },
        {
            "name": "ef_construct_as_string",
            "payload": {
                "vectors": {"size": 128, "distance": "Cosine"},
                "hnsw_config": {"ef_construct": "100"}
            },
            "should_accept": False,
            "desc": "String '100' instead of integer 100 for ef_construct"
        },
        {
            "name": "ef_construct_as_float",
            "payload": {
                "vectors": {"size": 128, "distance": "Cosine"},
                "hnsw_config": {"ef_construct": 100.7}
            },
            "should_accept": False,
            "desc": "Float 100.7 instead of integer 100 for ef_construct"
        },
        {
            "name": "ef_construct_as_bool",
            "payload": {
                "vectors": {"size": 128, "distance": "Cosine"},
                "hnsw_config": {"ef_construct": False}
            },
            "should_accept": False,
            "desc": "Boolean false instead of integer for ef_construct"
        },
    ]

    for i, test_case in enumerate(test_cases):
        collection_name = f"{collection_base}_{i}"

        print(f"\nTest: {test_case['name']}")
        print(f"Description: {test_case['desc']}")

        status, body, raw = safe_request(
            "PUT",
            f"/collections/{collection_name}",
            json_data=test_case["payload"]
        )

        print(f"Status: {status}")
        print(f"Response: {raw[:200] if raw else 'empty'}")

        # If it should be rejected
        if not test_case["should_accept"]:
            if status in (200, 201):
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)")
                print(f"Incorrect type was accepted: {test_case['desc']}")
                try:
                    safe_request("DELETE", f"/collections/{collection_name}")
                except:
                    pass
                sys.exit(1)
            else:
                print(f"✓ Correctly rejected (status {status})")
        else:
            if status not in (200, 201):
                print(f"WARNING: Valid type was rejected (status {status})")

    print("\nVERDICT: NO_DEFECT")
    print("All HNSW type coercion tests passed - incorrect types are properly rejected")

if __name__ == "__main__":
    test_type_coercion_hnsw_config()
