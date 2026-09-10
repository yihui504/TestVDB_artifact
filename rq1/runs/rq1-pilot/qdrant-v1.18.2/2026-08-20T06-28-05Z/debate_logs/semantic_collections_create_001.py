"""
Test: Behavioral Contract - Valid Collection Creation
Attack: Behavioral Contract Violation
Verifies that valid collection configuration returns 200 OK per contract
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

def test_valid_collection_creation():
    """Verify valid collection configuration returns 200 OK"""
    collection_name = "test_valid_creation"

    # Valid configuration per contract
    payload = {
        "vectors": {
            "size": 128,
            "distance": "Cosine"
        },
        "hnsw_config": {
            "m": 16,
            "ef_construct": 100
        }
    }

    print(f"Creating collection with valid config: size=128, distance=Cosine")
    status, body, raw = safe_request(
        "PUT",
        f"/collections/{collection_name}",
        json_data=payload
    )

    print(raw)

    if status != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure)")
        print(f"Expected 200 OK for valid collection config, got status={status}")
        print(f"Body: {raw}")
        sys.exit(1)

    # Verify collection exists
    status_check, body_check, raw_check = safe_request(
        "GET",
        f"/collections/{collection_name}"
    )

    if status_check != 200:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"Collection creation returned 200 but GET check failed with status={status_check}")
        sys.exit(1)

    # Cleanup
    try:
        safe_request("DELETE", f"/collections/{collection_name}")
    except:
        pass

    print("VERDICT: NO_DEFECT")
    print("Valid collection creation properly returns 200 OK and collection is visible")

if __name__ == "__main__":
    test_valid_collection_creation()
