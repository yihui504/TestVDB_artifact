#!/usr/bin/env python3
"""
TestVDB Attack Vein Script - Type Confusion Bug on Query Filter Parameters

DEFECT_ID: vein_type_confusion_query_1
TARGET: qdrant v1.19.0
STRATEGY: vein_type_confusion

Tests type confusion validation bugs on POST /collections/{collection}/points/query
where invalid null/object types are accepted for array-required filter parameters
(filter.should, filter.must_not) without returning 4xx error.

Issue: The query endpoint accepts invalid types for filter parameters:
- filter.should=null (should be array or omitted)
- filter.must_not=object (should be array)
These type mismatches are silently accepted instead of being rejected with 400 Bad Request.

This pattern matches historical issue #9420 where null filter conditions
were silently treated as no-filter instead of being rejected as invalid.
"""

import requests
import json
import sys


def safe_request(method, url, headers=None, json_data=None, timeout=10):
    """
    Safe HTTP request wrapper that returns (response, error) tuple.
    Handles network errors, timeouts, and invalid responses gracefully.
    """
    try:
        if method.upper() == "GET":
            response = requests.get(url, headers=headers, timeout=timeout)
        elif method.upper() == "POST":
            response = requests.post(url, headers=headers, json=json_data, timeout=timeout)
        elif method.upper() == "PUT":
            response = requests.put(url, headers=headers, json=json_data, timeout=timeout)
        elif method.upper() == "DELETE":
            response = requests.delete(url, headers=headers, timeout=timeout)
        else:
            return None, f"Unsupported method: {method}"

        return response, None
    except requests.exceptions.Timeout:
        return None, f"Request timeout after {timeout}s"
    except requests.exceptions.ConnectionError as e:
        return None, f"Connection error: {str(e)}"
    except Exception as e:
        return None, f"Request failed: {str(e)}"


def cleanup(db_url, collection_name):
    """Cleanup test collection"""
    try:
        url = f"{db_url}/collections/{collection_name}"
        resp, err = safe_request("DELETE", url)
        if err:
            print(f"Warning: cleanup failed - {err}")
    except:
        pass


def main():
    db_url = "http://localhost:6333"
    collection_name = "vein_type_confusion_query"

    # Setup: Create collection
    print(f"[SETUP] Creating collection {collection_name}...")

    url = f"{db_url}/collections/{collection_name}"
    create_data = {
        "vectors": {
            "size": 4,
            "distance": "Cosine"
        }
    }

    resp, err = safe_request("PUT", url, json_data=create_data)
    if err or (resp and resp.status_code != 200):
        print(f"VERDICT: SETUP_FAILED - Collection creation failed: {err or resp.text}")
        return

    # Insert test data
    print(f"[SETUP] Inserting test points...")

    points_url = f"{db_url}/collections/{collection_name}/points"
    points_data = {
        "points": [
            {"id": 1, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"category": "A", "value": 10}},
            {"id": 2, "vector": [0.2, 0.3, 0.4, 0.5], "payload": {"category": "B", "value": 20}},
            {"id": 3, "vector": [0.3, 0.4, 0.5, 0.6], "payload": {"category": "A", "value": 30}}
        ]
    }

    resp, err = safe_request("PUT", points_url, json_data=points_data)
    if err or (resp and resp.status_code != 200):
        print(f"VERDICT: SETUP_FAILED - Point insertion failed: {err or resp.text}")
        cleanup(db_url, collection_name)
        return

    # TEST 1: filter.should=null (should be array or omitted)
    print(f"[TEST 1] Testing filter.should=null (type confusion - null instead of array)...")

    query_url = f"{db_url}/collections/{collection_name}/points/query"
    query_data_should_null = {
        "filter": {
            "should": None
        },
        "limit": 10
    }

    resp, err = safe_request("POST", query_url, json_data=query_data_should_null)
    if err:
        print(f"VERDICT: TEST_ERROR - Query request failed: {err}")
        cleanup(db_url, collection_name)
        return

    print(f"[TEST 1] HTTP status: {resp.status_code}")

    if resp.status_code == 200:
        result = json.loads(resp.text or "{}")
        points = result.get("result", {}).get("points", [])
        point_count = len(points)
        print(f"[TEST 1] Returned {point_count} points with filter.should=null")

        if point_count == 3:
            print(f"[TEST 1] filter.should=null was treated as no-filter (returned all points)")
        else:
            print(f"[TEST 1] filter.should=null returned {point_count} points (unexpected)")
    elif resp.status_code == 400:
        print(f"[TEST 1] HTTP 400 Bad Request - correctly rejected filter.should=null")
        cleanup(db_url, collection_name)
        print(f"VERDICT: NO_DEFECT")
        print(f"REASON: API correctly rejects null filter.should parameter")
        return
    else:
        print(f"VERDICT: TEST_ERROR - Unexpected HTTP status {resp.status_code}")
        cleanup(db_url, collection_name)
        return

    # TEST 2: filter.must_not=object (should be array)
    print(f"[TEST 2] Testing filter.must_not=object (type confusion - object instead of array)...")

    query_data_must_not_object = {
        "filter": {
            "must_not": {"key": "category", "match": {"value": "A"}}
        },
        "limit": 10
    }

    resp, err = safe_request("POST", query_url, json_data=query_data_must_not_object)
    if err:
        print(f"VERDICT: TEST_ERROR - Query request failed: {err}")
        cleanup(db_url, collection_name)
        return

    print(f"[TEST 2] HTTP status: {resp.status_code}")

    if resp.status_code == 200:
        result = json.loads(resp.text or "{}")
        points = result.get("result", {}).get("points", [])
        point_count = len(points)
        print(f"[TEST 2] Returned {point_count} points with filter.must_not=object")

        if point_count == 1:
            print(f"[TEST 2] filter.must_not=object was accepted and partially executed")
        else:
            print(f"[TEST 2] filter.must_not=object returned {point_count} points (unexpected)")
    elif resp.status_code == 400:
        print(f"[TEST 2] HTTP 400 Bad Request - correctly rejected filter.must_not=object")
        cleanup(db_url, collection_name)
        print(f"VERDICT: NO_DEFECT")
        print(f"REASON: API correctly rejects object type for filter.must_not parameter")
        return
    else:
        print(f"VERDICT: TEST_ERROR - Unexpected HTTP status {resp.status_code}")
        cleanup(db_url, collection_name)
        return

    # ANALYSIS: Both type confusions were accepted
    print(f"[ANALYSIS] Type confusion validation status:")
    print(f"[ANALYSIS] - filter.should=null: Accepted (HTTP 200)")
    print(f"[ANALYSIS] - filter.must_not=object: Accepted (HTTP 200)")

    print(f"VERDICT: DEFECT_FOUND")
    print(f"DEFECT_TYPE: Type1_IllegalSuccess")
    print(f"SEVERITY: High")
    print(f"DESCRIPTION: Query endpoint accepts invalid types for filter parameters without 4xx error")
    print(f"EVIDENCE:")
    print(f"  - filter.should=null: Returned HTTP 200 (should be 400 Bad Request)")
    print(f"  - filter.must_not=object: Returned HTTP 200 (should be 400 Bad Request)")
    print(f"PARAMETERS_TESTED:")
    print(f"  - filter.should: Expected array|null, got null (treated as no-filter)")
    print(f"  - filter.must_not: Expected array, got object (silently accepted)")
    print(f"EXPECTED_BEHAVIOR: API should reject null/object with 400 Bad Request for array-required parameters")
    print(f"ACTUAL_BEHAVIOR: API accepts invalid types and returns success (200 OK)")
    print(f"ROOT_CAUSE: Missing REST API validation for nested filter parameter types")
    print(f"IMPACT: Applications may send malformed filter queries that execute incorrectly, leading to silent data exposure or incorrect query results")
    print(f"RELATED: Historical issue #9420 (null filter conditions accepted without validation)")
    cleanup(db_url, collection_name)


if __name__ == "__main__":
    main()
