#!/usr/bin/env python3
"""
TestVDB Attack Script: vein_range_filter_replication
Target: weaviate v1.37.4
Endpoint: POST /v1/replication/scale
Condition: range_filter on replicationFactor

Testing: Replication scaling with invalid replicationFactor values
Expected: Should validate replicationFactor is positive integer
Defect Type: Type1_IllegalSuccess (if accepts invalid values)
"""

import requests
import json

DB_URL = "http://localhost:8080"
COLLECTION_NAME = "VeinTestReplication"

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
    """Create test collection with replication"""
    schema = {
        "class": COLLECTION_NAME,
        "vectorizer": "none",
        "properties": [
            {
                "name": "text",
                "dataType": ["text"]
            }
        ],
        "replicationConfig": {
            "factor": 1
        }
    }
    result = safe_request("POST", "/v1/schema", json=schema, headers={"Content-Type": "application/json"})
    if result['status_code'] not in [200, 201]:
        print(f"Failed to create collection: {result['body']}")
        return False
    return True

def test_replication_factor_zero():
    """Test 1: Replication factor of 0"""
    print("\n[TEST 1] Testing replicationFactor = 0")

    payload = {
        "collection": COLLECTION_NAME,
        "replicationFactor": 0
    }

    result = safe_request(
        "POST",
        "/v1/replication/scale",
        json=payload,
        headers={"Content-Type": "application/json"}
    )

    print(f"  Status: {result['status_code']}")
    if result['status_code'] in [200, 202]:
        print("  !! DEFECT: Server accepted replicationFactor=0")
        return "DEFECT_FOUND"
    elif result['status_code'] in [400, 422]:
        print("  + Correctly rejected with 4xx")
        return "REJECTED"
    else:
        print(f"  ? Unexpected response: {result['body'][:200]}")
        return "UNKNOWN"

def test_replication_factor_negative():
    """Test 2: Negative replication factor"""
    print("\n[TEST 2] Testing negative replicationFactor")

    payload = {
        "collection": COLLECTION_NAME,
        "replicationFactor": -1
    }

    result = safe_request(
        "POST",
        "/v1/replication/scale",
        json=payload,
        headers={"Content-Type": "application/json"}
    )

    print(f"  Status: {result['status_code']}")
    if result['status_code'] in [200, 202]:
        print("  !! DEFECT: Server accepted negative replicationFactor")
        return "DEFECT_FOUND"
    elif result['status_code'] in [400, 422]:
        print("  + Correctly rejected with 4xx")
        return "REJECTED"
    else:
        print(f"  ? Unexpected response: {result['body'][:200]}")
        return "UNKNOWN"

def test_replication_factor_excessive():
    """Test 3: Excessively large replication factor"""
    print("\n[TEST 3] Testing excessive replicationFactor")

    payload = {
        "collection": COLLECTION_NAME,
        "replicationFactor": 999999
    }

    result = safe_request(
        "POST",
        "/v1/replication/scale",
        json=payload,
        headers={"Content-Type": "application/json"}
    )

    print(f"  Status: {result['status_code']}")
    if result['status_code'] in [200, 202]:
        print("  !! DEFECT: Server accepted excessive replicationFactor without validation")
        return "DEFECT_FOUND"
    elif result['status_code'] in [400, 422]:
        print("  + Correctly rejected with 4xx")
        return "REJECTED"
    else:
        print(f"  ? Unexpected response: {result['body'][:200]}")
        return "UNKNOWN"

def test_replication_factor_nonexistent_collection():
    """Test 4: Replication scale on nonexistent collection"""
    print("\n[TEST 4] Testing replication scale on nonexistent collection")

    payload = {
        "collection": "NonExistentCollection123",
        "replicationFactor": 2
    }

    result = safe_request(
        "POST",
        "/v1/replication/scale",
        json=payload,
        headers={"Content-Type": "application/json"}
    )

    print(f"  Status: {result['status_code']}")
    if result['status_code'] in [200, 202]:
        print("  !! DEFECT: Server accepted scale on nonexistent collection")
        return "DEFECT_FOUND"
    elif result['status_code'] in [404, 400, 422]:
        print("  + Correctly rejected with 4xx/404")
        return "REJECTED"
    else:
        print(f"  ? Unexpected response: {result['body'][:200]}")
        return "UNKNOWN"

def main():
    print("="*60)
    print("TestVDB Vein Mining: range_filter on replication")
    print("Target: weaviate v1.37.4")
    print("="*60)

    # Setup
    cleanup()
    if not setup_collection():
        print("Failed to setup test collection")
        return

    findings = []

    # Run all tests
    findings.append(("Zero Replication Factor", test_replication_factor_zero()))
    findings.append(("Negative Replication Factor", test_replication_factor_negative()))
    findings.append(("Excessive Replication Factor", test_replication_factor_excessive()))
    findings.append(("Nonexistent Collection", test_replication_factor_nonexistent_collection()))

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
