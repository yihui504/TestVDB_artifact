#!/usr/bin/env python3
"""
semantic_points_search_008
Attack: filter_semantics
Testing: points+search with filter conditions works correctly
Expected: Type4_StateLogicViolation if filter doesn't properly restrict results
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
    """Create test collection with filtered data"""
    collection_name = "test_search_semantic_008"

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

    # Insert points with different categories
    points = [
        {"id": 1, "vector": [0.1] * 128, "payload": {"category": "A", "score": 10}},
        {"id": 2, "vector": [0.1] * 128, "payload": {"category": "B", "score": 20}},
        {"id": 3, "vector": [0.1] * 128, "payload": {"category": "A", "score": 30}},
        {"id": 4, "vector": [0.1] * 128, "payload": {"category": "B", "score": 40}},
    ]

    status, _, raw = safe_request("PUT", f"/collections/{collection_name}/points", json_data={"points": points})
    if status not in (200, 201, 204):
        print(f"VERDICT: SCRIPT_ERROR — failed to insert points: {status}")
        sys.exit(2)

    return collection_name

def cleanup_test_collection(collection_name):
    """Clean up test collection"""
    try:
        safe_request("DELETE", f"/collections/{collection_name}")
    except:
        pass

def test_search_filter_semantics():
    """Test that search filters work correctly"""
    collection_name = setup_test_collection()

    try:
        # Test 1: Filter by category A
        search_payload = {
            "vector": [0.1] * 128,
            "limit": 10,
            "filter": {
                "must": [
                    {"key": "category", "match": {"value": "A"}}
                ]
            }
        }

        SEARCH_PATH = f"/collections/{collection_name}/points/search"
        status, body, raw = safe_request("POST", SEARCH_PATH, json_data=search_payload)

        print(f"Test 1 - Filter category=A: status={status}")
        print(f"Raw: {raw[:500]}")

        if status != 200:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"Filtered search should return 200 OK, got {status}")
            sys.exit(1)

        if not isinstance(body, list):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"Search should return array")
            sys.exit(1)

        # Should return exactly 2 results (category A)
        if len(body) != 2:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"Filter category=A should return 2 results, got {len(body)}")
            sys.exit(1)

        # Verify all results are category A
        for result in body:
            payload = result.get("payload", {})
            if payload.get("category") != "A":
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
                print(f"Filtered result has wrong category: {payload.get('category')}")
                sys.exit(1)

        # Test 2: Filter by score > 15
        search_payload = {
            "vector": [0.1] * 128,
            "limit": 10,
            "filter": {
                "must": [
                    {"key": "score", "range": {"gt": 15}}
                ]
            }
        }

        status, body, raw = safe_request("POST", SEARCH_PATH, json_data=search_payload)

        print(f"Test 2 - Filter score>15: status={status}")

        if status != 200:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"Filtered search should return 200 OK, got {status}")
            sys.exit(1)

        # Should return exactly 2 results (id 3 and 4)
        if len(body) != 2:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"Filter score>15 should return 2 results, got {len(body)}")
            sys.exit(1)

        # Verify all results have score > 15
        for result in body:
            payload = result.get("payload", {})
            score = payload.get("score", 0)
            if score <= 15:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
                print(f"Filtered result has score={score}, should be >15")
                sys.exit(1)

        print("VERDICT: NO_DEFECT")

    finally:
        cleanup_test_collection(collection_name)

if __name__ == "__main__":
    test_search_filter_semantics()
