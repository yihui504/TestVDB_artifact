"""
Test: Type Coercion - Vectors Config Parameters
Attack: Type Confusion (Type-1)
Tests implicit type conversion for numeric parameters in vectors config
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

def test_type_coercion_vectors_config():
    """Test that vectors config parameters don't accept incorrect types"""
    collection_base = "test_type_coercion"

    # Test cases: vectors.size should be integer, not string/float/bool
    test_cases = [
        {
            "name": "size_as_string",
            "payload": {"vectors": {"size": "128", "distance": "Cosine"}},
            "should_accept": False,
            "desc": "String '128' instead of integer 128"
        },
        {
            "name": "size_as_float",
            "payload": {"vectors": {"size": 128.5, "distance": "Cosine"}},
            "should_accept": False,
            "desc": "Float 128.5 instead of integer 128"
        },
        {
            "name": "size_as_bool",
            "payload": {"vectors": {"size": True, "distance": "Cosine"}},
            "should_accept": False,
            "desc": "Boolean true instead of integer"
        },
        {
            "name": "distance_as_number",
            "payload": {"vectors": {"size": 128, "distance": 123}},
            "should_accept": False,
            "desc": "Number 123 instead of string 'Cosine'"
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
                print(f"Payload: {test_case['payload']}")
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
    print("All type coercion tests passed - incorrect types are properly rejected")

if __name__ == "__main__":
    test_type_coercion_vectors_config()
