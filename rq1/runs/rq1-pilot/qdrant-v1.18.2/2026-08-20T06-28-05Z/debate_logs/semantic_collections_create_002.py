"""
Test: Behavioral Contract - Duplicate Collection Creation
Attack: Behavioral Contract Violation
Verifies that creating an existing collection returns 400 Bad Request per contract
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

def test_duplicate_collection_creation():
    """Verify creating existing collection returns 400 Bad Request"""
    collection_name = "test_duplicate_creation"

    payload = {
        "vectors": {
            "size": 128,
            "distance": "Cosine"
        }
    }

    # Create collection first time
    print("Creating collection first time...")
    status1, body1, raw1 = safe_request(
        "PUT",
        f"/collections/{collection_name}",
        json_data=payload
    )

    if status1 not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — Initial creation failed: {status1}")
        print(raw1)
        sys.exit(2)

    print(f"First creation succeeded with status {status1}")

    # Try to create again with same name
    print("Attempting duplicate creation...")
    status2, body2, raw2 = safe_request(
        "PUT",
        f"/collections/{collection_name}",
        json_data=payload
    )

    print(f"Second creation response: {raw2}")

    if status2 == 400:
        print("VERDICT: NO_DEFECT")
        print("Duplicate collection creation properly returns 400 Bad Request")
    elif status2 in (200, 201):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"Expected 400 Bad Request for duplicate collection, got {status2}")
        print(f"Contract violation: Creating existing collection should fail")
        sys.exit(1)
    else:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure)")
        print(f"Expected 400 Bad Request for duplicate collection, got unexpected status {status2}")
        sys.exit(1)

    # Cleanup
    try:
        safe_request("DELETE", f"/collections/{collection_name}")
    except:
        pass

if __name__ == "__main__":
    test_duplicate_collection_creation()
