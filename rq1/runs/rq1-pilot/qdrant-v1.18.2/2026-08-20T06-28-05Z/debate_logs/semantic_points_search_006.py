#!/usr/bin/env python3
"""
semantic_points_search_006
Attack: search_correctness
Testing: points+search returns correct nearest neighbors by score
Expected: Type4_StateLogicViolation if results aren't ordered by similarity
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
    """Create test collection with vectors at known distances"""
    collection_name = "test_search_semantic_006"

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

    # Insert vectors at known distances from query [0.1, 0.1, ...]
    # Closest: [0.1]*128 (distance = 0)
    # Medium: [0.2]*128 (distance = small)
    # Far: [1.0]*128 (distance = large)
    points = [
        {"id": "target", "vector": [0.1] * 128},      # Exact match
        {"id": "close", "vector": [0.11] * 128},     # Very close
        {"id": "medium", "vector": [0.3] * 128},     # Medium distance
        {"id": "far", "vector": [0.9] * 128},        # Far
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

def test_search_correctness():
    """Test that search returns results ordered by similarity score"""
    collection_name = setup_test_collection()

    try:
        query = [0.1] * 128
        search_payload = {
            "vector": query,
            "limit": 4
        }

        SEARCH_PATH = f"/collections/{collection_name}/points/search"
        status, body, raw = safe_request("POST", SEARCH_PATH, json_data=search_payload)

        print(f"Status: {status}")
        print(f"Raw response: {raw[:800]}")

        if status != 200:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"Search should return 200 OK, got {status}")
            sys.exit(1)

        if not isinstance(body, list) or len(body) == 0:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"Search should return non-empty array of results")
            sys.exit(1)

        # Verify results are ordered by score (highest similarity = lowest distance for Cosine)
        # For Cosine, higher score = more similar
        prev_score = float('inf')
        for i, result in enumerate(body):
            if "score" not in result:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
                print(f"Result {i} missing score field")
                sys.exit(1)

            score = result["score"]
            print(f"Result {i}: id={result.get('id')}, score={score}")

            # Scores should be in descending order (most similar first)
            if i > 0 and score > prev_score:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
                print(f"Results not ordered by similarity: score {score} > prev_score {prev_score}")
                sys.exit(1)

            prev_score = score

        # First result should be "target" (exact match)
        first_id = body[0].get("id")
        if first_id != "target":
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"First result should be 'target' (exact match), got '{first_id}'")
            sys.exit(1)

        print("VERDICT: NO_DEFECT")

    finally:
        cleanup_test_collection(collection_name)

if __name__ == "__main__":
    test_search_correctness()
