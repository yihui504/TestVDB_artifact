#!/usr/bin/env python3
"""
semantic_points_search_009
Attack: behavioral_contract
Testing: points+search with score_threshold filters results correctly
Expected: Type4_StateLogicViolation if score_threshold doesn't filter properly
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
    """Create test collection"""
    collection_name = "test_search_semantic_009"

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

    # Insert vectors at varying distances
    points = [
        {"id": 1, "vector": [0.1] * 128},      # Will be closest to query
        {"id": 2, "vector": [0.5] * 128},      # Medium distance
        {"id": 3, "vector": [0.9] * 128},      # Far
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

def test_search_score_threshold():
    """Test that score_threshold filters results correctly"""
    collection_name = setup_test_collection()

    try:
        query = [0.1] * 128

        # First, get unfiltered results to understand baseline scores
        search_payload = {
            "vector": query,
            "limit": 10
        }

        SEARCH_PATH = f"/collections/{collection_name}/points/search"
        status, body, raw = safe_request("POST", SEARCH_PATH, json_data=search_payload)

        if status != 200 or not isinstance(body, list):
            print(f"VERDICT: SCRIPT_ERROR — unfiltered search failed")
            sys.exit(2)

        baseline_scores = [r.get("score", 0) for r in body]
        print(f"Baseline scores: {baseline_scores}")

        # Test with a high score_threshold (should filter out low-similarity results)
        # For Cosine distance, higher score = more similar
        # Set threshold to filter out at least one result
        threshold = 0.5

        search_payload = {
            "vector": query,
            "limit": 10,
            "score_threshold": threshold
        }

        status, body, raw = safe_request("POST", SEARCH_PATH, json_data=search_payload)

        print(f"Search with score_threshold={threshold}: status={status}")
        print(f"Raw: {raw[:500]}")

        if status != 200:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"Search with score_threshold should return 200 OK, got {status}")
            sys.exit(1)

        if not isinstance(body, list):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"Search should return array")
            sys.exit(1)

        # Verify all returned scores meet the threshold
        for i, result in enumerate(body):
            score = result.get("score", 0)
            print(f"Result {i}: score={score}")

            if score < threshold:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
                print(f"Result score {score} is below threshold {threshold}")
                sys.exit(1)

        # Results with threshold should be <= results without threshold
        # (or equal if all meet threshold)
        if len(body) > len(baseline_scores):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"Filtered results ({len(body)}) > baseline ({len(baseline_scores)})")
            sys.exit(1)

        print("VERDICT: NO_DEFECT")

    finally:
        cleanup_test_collection(collection_name)

if __name__ == "__main__":
    test_search_score_threshold()
