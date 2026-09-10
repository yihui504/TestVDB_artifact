#!/usr/bin/env python3
"""
TestVDB Attack Script: vein_range_filter_numeric_config
Target: weaviate v1.37.4
Endpoint: POST /v1/schema
Condition: range_filter on vectorIndexConfig numeric parameters

Testing: dynamicEfMin/dynamicEfMax parameter boundary conditions
Expected: Should validate Min <= Max constraint
Defect Type: Type1_IllegalSuccess (if accepts invalid boundaries)
"""

import requests
import json

DB_URL = "http://localhost:8080"
COLLECTION_NAME = "VeinTestRangeFilterNumeric"

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

def test_range_boundary_inverted():
    """Test 1: dynamicEfMin > dynamicEfMax (inverted range)"""
    print("\n[TEST 1] Testing inverted range: Min > Max")

    schema = {
        "class": COLLECTION_NAME,
        "vectorizer": "none",
        "properties": [
            {
                "name": "text",
                "dataType": ["text"]
            }
        ],
        "vectorIndexConfig": {
            "dynamicEfMin": 500,
            "dynamicEfMax": 100
        }
    }

    result = safe_request(
        "POST",
        "/v1/schema",
        json=schema,
        headers={"Content-Type": "application/json"}
    )

    print(f"  Status: {result['status_code']}")
    if result['status_code'] == 200:
        print("  !! DEFECT: Server accepted inverted range (Min > Max)")
        return "DEFECT_FOUND"
    elif result['status_code'] in [400, 422]:
        print("  + Correctly rejected with 4xx")
        return "REJECTED"
    else:
        print(f"  ? Unexpected response: {result['body'][:200]}")
        return "UNKNOWN"

def test_range_boundary_negative():
    """Test 2: Negative boundary values"""
    print("\n[TEST 2] Testing negative boundaries")

    schema = {
        "class": COLLECTION_NAME + "_Neg",
        "vectorizer": "none",
        "properties": [
            {
                "name": "text",
                "dataType": ["text"]
            }
        ],
        "vectorIndexConfig": {
            "dynamicEfMin": -100,
            "dynamicEfMax": 100
        }
    }

    result = safe_request(
        "POST",
        "/v1/schema",
        json=schema,
        headers={"Content-Type": "application/json"}
    )

    print(f"  Status: {result['status_code']}")
    if result['status_code'] == 200:
        print("  !! DEFECT: Server accepted negative EF values")
        return "DEFECT_FOUND"
    elif result['status_code'] in [400, 422]:
        print("  + Correctly rejected with 4xx")
        return "REJECTED"
    else:
        print(f"  ? Unexpected response: {result['body'][:200]}")
        return "UNKNOWN"

def test_range_boundary_equal():
    """Test 3: Equal boundaries (Min = Max, edge case)"""
    print("\n[TEST 3] Testing equal boundaries: Min = Max")

    schema = {
        "class": COLLECTION_NAME + "_Eq",
        "vectorizer": "none",
        "properties": [
            {
                "name": "text",
                "dataType": ["text"]
            }
        ],
        "vectorIndexConfig": {
            "dynamicEfMin": 100,
            "dynamicEfMax": 100
        }
    }

    result = safe_request(
        "POST",
        "/v1/schema",
        json=schema,
        headers={"Content-Type": "application/json"}
    )

    print(f"  Status: {result['status_code']}")
    if result['status_code'] == 200:
        print("  + Accepted equal boundaries (may be valid)")
        # Verify collection was created
        verify = safe_request("GET", f"/v1/schema/{COLLECTION_NAME}_Eq")
        if verify['status_code'] == 200:
            print("  - Collection successfully created with equal boundaries")
            return "ACCEPTED_VALID"
        else:
            print("  ? Collection creation may have issues")
            return "UNKNOWN"
    elif result['status_code'] in [400, 422]:
        print("  - Rejected equal boundaries (may be overly strict)")
        return "REJECTED"
    else:
        print(f"  ? Unexpected response: {result['body'][:200]}")
        return "UNKNOWN"

def test_range_boundary_zero():
    """Test 4: Zero boundary values"""
    print("\n[TEST 4] Testing zero boundaries")

    schema = {
        "class": COLLECTION_NAME + "_Zero",
        "vectorizer": "none",
        "properties": [
            {
                "name": "text",
                "dataType": ["text"]
            }
        ],
        "vectorIndexConfig": {
            "dynamicEfMin": 0,
            "dynamicEfMax": 100
        }
    }

    result = safe_request(
        "POST",
        "/v1/schema",
        json=schema,
        headers={"Content-Type": "application/json"}
    )

    print(f"  Status: {result['status_code']}")
    if result['status_code'] == 200:
        print("  !! DEFECT: Server accepted zero EF (should require positive integer)")
        return "DEFECT_FOUND"
    elif result['status_code'] in [400, 422]:
        print("  + Correctly rejected with 4xx")
        return "REJECTED"
    else:
        print(f"  ? Unexpected response: {result['body'][:200]}")
        return "UNKNOWN"

def main():
    print("="*60)
    print("TestVDB Vein Mining: range_filter on numeric config")
    print("Target: weaviate v1.37.4")
    print("="*60)

    # Cleanup any existing collections
    cleanup()

    findings = []

    # Run all tests
    findings.append(("Inverted Range", test_range_boundary_inverted()))
    findings.append(("Negative Values", test_range_boundary_negative()))
    findings.append(("Equal Boundaries", test_range_boundary_equal()))
    findings.append(("Zero Values", test_range_boundary_zero()))

    # Cleanup
    cleanup()
    safe_request("DELETE", f"/v1/schema/{COLLECTION_NAME}_Neg")
    safe_request("DELETE", f"/v1/schema/{COLLECTION_NAME}_Eq")
    safe_request("DELETE", f"/v1/schema/{COLLECTION_NAME}_Zero")

    # Summary
    print("\n" + "="*60)
    print("FINDINGS SUMMARY")
    print("="*60)
    for test_name, verdict in findings:
        marker = "✗" if verdict == "DEFECT_FOUND" else "✓" if verdict == "REJECTED" else "?"
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
