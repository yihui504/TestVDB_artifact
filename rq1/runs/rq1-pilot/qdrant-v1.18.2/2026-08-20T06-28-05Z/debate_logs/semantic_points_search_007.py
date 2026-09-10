#!/usr/bin/env python3
"""
semantic_points_search_007
Attack: diagnosis_quality
Testing: points+search with out-of-range limit returns clear error
Expected: Type2_PoorDiagnostics if error doesn't specify valid range
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

def check_error_quality(status, body, expected_param):
    """
    Type-2 diagnosis quality rubric:
    - Must mention limit parameter (1pt)
    - Should indicate valid range (1pt)
    - Bonus: actionable suggestion (1pt)
    """
    error_msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()

    score = 0
    max_score = 3

    # Criterion 1: Parameter named
    if expected_param and expected_param.lower() in error_msg:
        score += 1

    # Criterion 2: Range indication
    if any(kw in error_msg for kw in ["range", "between", "maximum", "minimum", "1", "1000"]):
        score += 1

    # Criterion 3: Actionable suggestion
    if any(kw in error_msg for kw in ["use", "try", "value", "between", "valid"]):
        score += 1

    return score, max_score

def setup_test_collection():
    """Create test collection"""
    collection_name = "test_search_semantic_007"

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

    return collection_name

def cleanup_test_collection(collection_name):
    """Clean up test collection"""
    try:
        safe_request("DELETE", f"/collections/{collection_name}")
    except:
        pass

def test_search_limit_range_error_quality():
    """Test that out-of-range limit returns high-quality error"""
    collection_name = setup_test_collection()

    try:
        # Test out-of-range values (constraint: limit ∈ [1, 1000])
        test_cases = [
            ("zero", 0),
            ("negative", -1),
            ("too large", 1001),
            ("way too large", 10000),
        ]

        for desc, limit in test_cases:
            search_payload = {
                "vector": [0.1] * 128,
                "limit": limit
            }

            SEARCH_PATH = f"/collections/{collection_name}/points/search"
            status, body, raw = safe_request("POST", SEARCH_PATH, json_data=search_payload)

            print(f"Testing limit={limit} ({desc}): status={status}")

            if status >= 400:
                score, max_score = check_error_quality(body, "limit")

                print(f"  Error quality score: {score}/{max_score}")

                if score < 2:
                    print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics)")
                    print(f"Error for limit={limit} lacks diagnostic quality")
                    print(f"Score {score}/{max_score} - minimum 2 required")
                    sys.exit(1)

        print("VERDICT: NO_DEFECT")

    finally:
        cleanup_test_collection(collection_name)

if __name__ == "__main__":
    test_search_limit_range_error_quality()
