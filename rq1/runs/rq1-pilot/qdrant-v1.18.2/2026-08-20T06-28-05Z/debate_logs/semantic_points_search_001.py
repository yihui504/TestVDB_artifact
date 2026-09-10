#!/usr/bin/env python3
"""
semantic_points_search_001
Attack: behavioral_contract
Testing: points+search returns 200 OK with scored results on valid query
Expected: Type4_StateLogicViolation if search doesn't return properly scored results
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
    """Create a test collection with sample data for search testing"""
    collection_name = "test_search_semantic_001"

    # Create collection
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

    # Insert test points
    points = [
        {"id": 1, "vector": [0.1] * 128, "payload": {"category": "A"}},
        {"id": 2, "vector": [0.2] * 128, "payload": {"category": "B"}},
        {"id": 3, "vector": [0.15] * 128, "payload": {"category": "A"}},
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

def test_search_returns_scored_results():
    """Test that search returns properly scored results"""
    collection_name = setup_test_collection()

    try:
        # Perform search
        search_payload = {
            "vector": [0.1] * 128,
            "limit": 3,
            "with_payload": True
        }

        SEARCH_PATH = f"/collections/{collection_name}/points/search"
        status, body, raw = safe_request("POST", SEARCH_PATH, json_data=search_payload)

        print(f"Status: {status}")
        print(f"Raw response: {raw[:500]}")

        if status != 200:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"Search should return 200 OK on valid query, got {status}")
            sys.exit(1)

        # Verify response structure
        if not isinstance(body, list):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"Search should return array of scored points, got {type(body)}")
            sys.exit(1)

        if len(body) == 0:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"Search should return results, got empty array")
            sys.exit(1)

        # Verify result structure
        first_result = body[0]
        if not isinstance(first_result, dict):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"Each result should be an object with id and score")
            sys.exit(1)

        if "id" not in first_result:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"Each result must have 'id' field")
            sys.exit(1)

        if "score" not in first_result:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"Each result must have 'score' field for similarity")
            sys.exit(1)

        # Verify score is numeric
        score = first_result["score"]
        if not isinstance(score, (int, float)):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"Score must be numeric, got {type(score)}")
            sys.exit(1)

        print(f"VERDICT: NO_DEFECT")

    finally:
        cleanup_test_collection(collection_name)

if __name__ == "__main__":
    test_search_returns_scored_results()
