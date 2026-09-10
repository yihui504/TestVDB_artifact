#!/usr/bin/env python3
"""
semantic_points_search_010
Attack: illegal_rejection
Testing: points+search accepts valid score_threshold values
Expected: Type1_IllegalRejection if valid score_threshold values are rejected
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
    collection_name = "test_search_semantic_010"

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

    # Insert test point
    points = [{"id": 1, "vector": [0.1] * 128}]
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

def test_search_score_threshold_valid_values():
    """Test that search accepts various valid score_threshold values"""
    collection_name = setup_test_collection()

    try:
        # Test various valid score_threshold values (constraint: ∈ [0, 1])
        valid_thresholds = [0.0, 0.25, 0.5, 0.75, 0.99, 1.0]

        for threshold in valid_thresholds:
            search_payload = {
                "vector": [0.1] * 128,
                "limit": 10,
                "score_threshold": threshold
            }

            SEARCH_PATH = f"/collections/{collection_name}/points/search"
            status, body, raw = safe_request("POST", SEARCH_PATH, json_data=search_payload)

            print(f"Testing score_threshold={threshold}: status={status}")

            if status != 200:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection)")
                print(f"Valid score_threshold={threshold} was rejected with status {status}")
                print(f"Raw: {raw[:200]}")
                sys.exit(1)

        print("VERDICT: NO_DEFECT")

    finally:
        cleanup_test_collection(collection_name)

if __name__ == "__main__":
    test_search_score_threshold_valid_values()
