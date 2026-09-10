#!/usr/bin/env python3
"""
TestVDB Attack Script: vein_compound_and_batch
Target: weaviate v1.37.4
Endpoint: POST /v1/batch/objects
Condition: compound_and consistency levels

Testing: Batch operations with compound consistency requirements
Expected: Should validate consistency parameter combinations
Defect Type: Type1_IllegalSuccess (if accepts invalid combinations)
"""

import requests
import json
import uuid

DB_URL = "http://localhost:8080"
COLLECTION_NAME = "VeinTestCompoundBatch"

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
    """Create test collection"""
    schema = {
        "class": COLLECTION_NAME,
        "vectorizer": "none",
        "properties": [
            {
                "name": "name",
                "dataType": ["text"]
            },
            {
                "name": "value",
                "dataType": ["int"]
            }
        ]
    }
    result = safe_request("POST", "/v1/schema", json=schema, headers={"Content-Type": "application/json"})
    if result['status_code'] not in [200, 201]:
        print(f"Failed to create collection: {result['body']}")
        return False
    return True

def test_batch_with_invalid_consistency():
    """Test 1: Batch with invalid consistency level"""
    print("\n[TEST 1] Testing batch with invalid consistency level")

    objects = [
        {
            "class": COLLECTION_NAME,
            "properties": {
                "name": "test1",
                "value": 1
            }
        }
    ]

    result = safe_request(
        "POST",
        f"/v1/batch/objects?consistency=INVALID_LEVEL",
        json=objects,
        headers={"Content-Type": "application/json"}
    )

    print(f"  Status: {result['status_code']}")
    if result['status_code'] == 200:
        print("  !! DEFECT: Server accepted invalid consistency level")
        return "DEFECT_FOUND"
    elif result['status_code'] in [400, 422]:
        print("  + Correctly rejected with 4xx")
        return "REJECTED"
    else:
        print(f"  ? Unexpected response: {result['body'][:200]}")
        return "UNKNOWN"

def test_batch_with_tenant_consistency_mismatch():
    """Test 2: Batch with tenant but without consistency"""
    print("\n[TEST 2] Testing batch with tenant without consistency level")

    objects = [
        {
            "class": COLLECTION_NAME,
            "properties": {
                "name": "test2",
                "value": 2
            }
        }
    ]

    # Using tenant parameter without consistency (may require consistency for multi-tenant)
    result = safe_request(
        "POST",
        f"/v1/batch/objects?tenant=TestTenant",
        json=objects,
        headers={"Content-Type": "application/json"}
    )

    print(f"  Status: {result['status_code']}")
    if result['status_code'] == 200:
        print("  - Accepted tenant without explicit consistency (may be valid)")
        return "ACCEPTED"
    elif result['status_code'] in [400, 422]:
        print("  + Requires consistency with tenant (4xx rejection)")
        return "REJECTED"
    else:
        print(f"  ? Unexpected response: {result['body'][:200]}")
        return "UNKNOWN"

def test_batch_with_empty_array():
    """Test 3: Batch with empty object array"""
    print("\n[TEST 3] Testing batch with empty array")

    result = safe_request(
        "POST",
        "/v1/batch/objects",
        json=[],
        headers={"Content-Type": "application/json"}
    )

    print(f"  Status: {result['status_code']}")
    if result['status_code'] == 200:
        print("  + Accepted empty batch (may be valid no-op)")
        return "ACCEPTED"
    elif result['status_code'] in [400, 422]:
        print("  - Rejected empty batch (may require at least one object)")
        return "REJECTED"
    else:
        print(f"  ? Unexpected response: {result['body'][:200]}")
        return "UNKNOWN"

def test_batch_with_mixed_classes():
    """Test 4: Batch with mixed object classes"""
    print("\n[TEST 4] Testing batch with mixed classes")

    objects = [
        {
            "class": COLLECTION_NAME,
            "properties": {
                "name": "test4a",
                "value": 4
            }
        },
        {
            "class": "NonExistentClass",
            "properties": {
                "name": "test4b",
                "value": 5
            }
        }
    ]

    result = safe_request(
        "POST",
        "/v1/batch/objects",
        json=objects,
        headers={"Content-Type": "application/json"}
    )

    print(f"  Status: {result['status_code']}")
    if result['status_code'] in [200, 201]:
        print("  !! DEFECT: Server accepted mixed classes with nonexistent class")
        return "DEFECT_FOUND"
    elif result['status_code'] in [400, 404, 422]:
        print("  + Correctly rejected with 4xx")
        return "REJECTED"
    else:
        print(f"  ? Unexpected response: {result['body'][:200]}")
        return "UNKNOWN"

def main():
    print("="*60)
    print("TestVDB Vein Mining: compound_and on batch consistency")
    print("Target: weaviate v1.37.4")
    print("="*60)

    # Setup
    cleanup()
    if not setup_collection():
        print("Failed to setup test collection")
        return

    findings = []

    # Run all tests
    findings.append(("Invalid Consistency", test_batch_with_invalid_consistency()))
    findings.append(("Tenant without Consistency", test_batch_with_tenant_consistency_mismatch()))
    findings.append(("Empty Array", test_batch_with_empty_array()))
    findings.append(("Mixed Classes", test_batch_with_mixed_classes()))

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
    print(f"\nTotal defects found: {defect_count}/4")

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
