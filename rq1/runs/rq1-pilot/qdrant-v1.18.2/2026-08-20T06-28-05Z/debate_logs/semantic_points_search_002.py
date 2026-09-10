#!/usr/bin/env python3
"""
semantic_points_search_002
Attack: behavioral_contract,diagnosis_quality
Testing: points+search with mismatched vector dimension returns clear error
Expected: Type2_PoorDiagnostics if error doesn't specify dimension mismatch
Blindspot: BS-02 Error Message Negligence
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

def check_error_quality(status, body, expected_keywords):
    """
    Type-2 diagnosis quality rubric:
    - Must mention dimension (1pt)
    - Should indicate size mismatch (1pt)
    - Bonus: actionable suggestion (1pt)
    """
    error_msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()

    score = 0
    max_score = 3

    # Criterion 1: Dimension mentioned
    if any(kw in error_msg for kw in ["dimension", "size", "vector", "length"]):
        score += 1

    # Criterion 2: Mismatch indication
    if any(kw in error_msg for kw in ["mismatch", "expected", "should", "must", "match"]):
        score += 1

    # Criterion 3: Actionable suggestion
    if any(kw in error_msg for kw in ["use", "provide", "check", "ensure", "correct"]):
        score += 1

    return score, max_score

def setup_test_collection():
    """Create a test collection with 128-dim vectors"""
    collection_name = "test_search_semantic_002"

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

def test_search_dimension_mismatch_error_quality():
    """Test that search with wrong dimension returns high-quality error"""
    collection_name = setup_test_collection()

    try:
        # Try to search with wrong dimension (64 instead of 128)
        search_payload = {
            "vector": [0.1] * 64,  # Wrong dimension
            "limit": 10
        }

        SEARCH_PATH = f"/collections/{collection_name}/points/search"
        status, body, raw = safe_request("POST", SEARCH_PATH, json_data=search_payload)

        print(f"Status: {status}")
        print(f"Raw response: {raw[:500]}")

        # Should get an error (likely 400 Bad Request)
        if status >= 400:
            score, max_score = check_error_quality(body, ["dimension", "mismatch"])

            print(f"Error quality score: {score}/{max_score}")

            if score < 2:
                print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics)")
                print(f"Error message for dimension mismatch lacks diagnostic quality")
                print(f"Score {score}/{max_score} - minimum 2 required")
                sys.exit(1)

            print("VERDICT: NO_DEFECT")
            return

        # If no error, that's also OK (API might accept it)
        print(f"VERDICT: NO_DEFECT (API accepted dimension {len(search_payload['vector'])})")

    finally:
        cleanup_test_collection(collection_name)

if __name__ == "__main__":
    test_search_dimension_mismatch_error_quality()
