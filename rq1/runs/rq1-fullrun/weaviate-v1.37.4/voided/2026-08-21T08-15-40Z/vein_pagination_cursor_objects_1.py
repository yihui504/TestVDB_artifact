#!/usr/bin/env python3
"""
TestVDB Attack Script: vein_pagination_cursor_objects
Target: weaviate v1.37.4
Endpoint: GET /v1/objects
Condition: pagination_cursor on limit/offset parameters

Testing: Object listing with pagination edge cases
Expected: Should validate pagination parameters
Defect Type: Type1_IllegalSuccess (if accepts invalid values)
"""

import requests
import json

DB_URL = "http://localhost:8080"
COLLECTION_NAME = "VeinTestPagination"

def safe_request(method, endpoint, **kwargs):
    """Execute HTTP request with error handling and timeout"""
    url = f"{DB_URL}{endpoint}"
    try:
        response = requests.request(
            method=method,
            url=url,
            timeout=10,
            **kwargs
        )
        return {
            "status_code": response.status_code,
            "body": response.text,
            "headers": dict(response.headers)
        }
    except requests.exceptions.Timeout:
        return {
            "status_code": 408,
            "body": "Request timeout after 10s",
            "headers": {}
        }
    except requests.exceptions.ConnectionError as e:
        return {
            "status_code": 503,
            "body": f"Connection error: {str(e)}",
            "headers": {}
        }
    except Exception as e:
        return {
            "status_code": 500,
            "body": f"Unexpected error: {str(e)}",
            "headers": {}
        }

def cleanup():
    """Delete test collection if exists"""
    safe_request("DELETE", f"/v1/schema/{COLLECTION_NAME}")

def setup_collection():
    """Create test collection and populate with data"""
    schema = {
        "class": COLLECTION_NAME,
        "vectorizer": "none",
        "properties": [
            {
                "name": "name",
                "dataType": ["text"]
            }
        ]
    }
    result = safe_request("POST", "/v1/schema", json=schema, headers={"Content-Type": "application/json"})
    if result['status_code'] not in [200, 201]:
        print(f"Failed to create collection: {result['body']}")
        return False

    # Add some test objects
    for i in range(5):
        obj = {
            "class": COLLECTION_NAME,
            "properties": {
                "name": f"test{i}"
            }
        }
        safe_request("POST", "/v1/objects", json=obj, headers={"Content-Type": "application/json"})
    return True

def test_pagination_limit_zero():
    """Test 1: Pagination with limit=0"""
    print("\n[TEST 1] Testing limit=0")

    result = safe_request(
        "GET",
        f"/v1/objects?limit=0"
    )

    print(f"  Status: {result['status_code']}")
    if result['status_code'] == 200:
        body_json = json.loads(result['body'])
        result_count = len(body_json.get('objects', []))
        if result_count > 0:
            print(f"  !! DEFECT: limit=0 returned {result_count} objects (should be 0)")
            return "DEFECT_FOUND"
        else:
            print("  + Correctly returned 0 objects")
            return "ACCEPTED"
    elif result['status_code'] in [400, 422]:
        print("  + Rejected limit=0 with 4xx")
        return "REJECTED"
    else:
        print(f"  ? Unexpected response: {result['body'][:200]}")
        return "UNKNOWN"

def test_pagination_limit_negative():
    """Test 2: Pagination with negative limit"""
    print("\n[TEST 2] Testing negative limit")

    result = safe_request(
        "GET",
        f"/v1/objects?limit=-10"
    )

    print(f"  Status: {result['status_code']}")
    if result['status_code'] == 200:
        print("  !! DEFECT: Server accepted negative limit")
        return "DEFECT_FOUND"
    elif result['status_code'] in [400, 422]:
        print("  + Correctly rejected with 4xx")
        return "REJECTED"
    else:
        print(f"  ? Unexpected response: {result['body'][:200]}")
        return "UNKNOWN"

def test_pagination_limit_excessive():
    """Test 3: Pagination with excessively large limit"""
    print("\n[TEST 3] Testing excessive limit")

    result = safe_request(
        "GET",
        f"/v1/objects?limit=999999999999"
    )

    print(f"  Status: {result['status_code']}")
    if result['status_code'] == 200:
        print("  - Accepted excessive limit (may have internal cap)")
        body_json = json.loads(result['body'])
        result_count = len(body_json.get('objects', []))
        print(f"    Returned {result_count} objects")
        if result_count > 10000:
            print("  !! DEFECT: No reasonable cap on excessive limit")
            return "DEFECT_FOUND"
        return "ACCEPTED"
    elif result['status_code'] in [400, 422]:
        print("  + Correctly rejected with 4xx")
        return "REJECTED"
    else:
        print(f"  ? Unexpected response: {result['body'][:200]}")
        return "UNKNOWN"

def test_pagination_offset_negative():
    """Test 4: Pagination with negative offset"""
    print("\n[TEST 4] Testing negative offset")

    result = safe_request(
        "GET",
        f"/v1/objects?offset=-5"
    )

    print(f"  Status: {result['status_code']}")
    if result['status_code'] == 200:
        print("  !! DEFECT: Server accepted negative offset")
        return "DEFECT_FOUND"
    elif result['status_code'] in [400, 422]:
        print("  + Correctly rejected with 4xx")
        return "REJECTED"
    else:
        print(f"  ? Unexpected response: {result['body'][:200]}")
        return "UNKNOWN"

def test_pagination_after_invalid_cursor():
    """Test 5: Pagination with invalid after cursor"""
    print("\n[TEST 5] Testing invalid after cursor")

    result = safe_request(
        "GET",
        f"/v1/objects?after=invalid_cursor_uuid_format"
    )

    print(f"  Status: {result['status_code']}")
    if result['status_code'] == 200:
        print("  - Accepted invalid cursor (may ignore it)")
        return "ACCEPTED"
    elif result['status_code'] in [400, 422]:
        print("  + Correctly rejected with 4xx")
        return "REJECTED"
    else:
        print(f"  ? Unexpected response: {result['body'][:200]}")
        return "UNKNOWN"

def main():
    print("="*60)
    print("TestVDB Vein Mining: pagination_cursor on objects")
    print("Target: weaviate v1.37.4")
    print("="*60)

    # Setup
    cleanup()
    if not setup_collection():
        print("Failed to setup test collection")
        return

    findings = []

    # Run all tests
    findings.append(("Limit Zero", test_pagination_limit_zero()))
    findings.append(("Limit Negative", test_pagination_limit_negative()))
    findings.append(("Limit Excessive", test_pagination_limit_excessive()))
    findings.append(("Offset Negative", test_pagination_offset_negative()))
    findings.append(("Invalid Cursor", test_pagination_after_invalid_cursor()))

    # Cleanup
    cleanup()

    # Summary
    print("\n" + "="*60)
    print("FINDINGS SUMMARY")
    print("="*60)
    for test_name, verdict in findings:
        marker = "X" if verdict == "DEFECT_FOUND" else "+" if verdict == "REJECTED" else "?"
        print(f"{marker} {test_name}: {verdict}")

    defect_count = sum(1 for _, v in findings if v == "DEFECT_FOUND")
    print(f"\nTotal defects found: {defect_count}/5")

    if defect_count > 0:
        VERDICT = "DEFECT_FOUND"
    else:
        VERDICT = "NO_DEFECT"

    print(f"\nFINAL VERDICT: {VERDICT}")
    print("="*60)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
