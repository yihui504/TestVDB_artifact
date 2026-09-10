"""
Attack: Filter parameter nested structure validation
Strategy: diagnosis_quality + type_coercion
Endpoint: points+search
Constraint: qdrant_type_search_points_001 (vector dimension match)
Target: qdrant v1.18.2

Tests filter parameter nested structure handling:
1. Empty filter object
2. Null filter
3. Invalid filter structure (array instead of object)
4. Nested filter with invalid operators
5. Type coercion in filter values

Qdrant filter structure: {"must": [{"key": "field", "match": {"value": "x"}}]}

Blindspot: BS-02 (Error Message Negligence), BS-05 (Documentation Drift)
"""

import os, sys, json, time
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

COLLECTION = "test_search_filter_nested"
VECTOR_DIM = 128
VECTOR_KEY = "vector"
POINT_WRAP = "points"

def safe_request(method, path, json=None, params=None):
    """Safe request wrapper avoiding bare JSON chains"""
    url = f"{BASE_URL}/{path}"
    try:
        resp = requests.request(method, url, json=json, params=params, timeout=30)
        return resp.status_code, resp.json() if resp.text else None, resp.text
    except Exception as e:
        return 0, None, str(e)

def setup_collection():
    """Create test collection"""
    status, body, raw = safe_request("PUT", "collections/" + COLLECTION, json={
        "vectors": {
            "size": VECTOR_DIM,
            "distance": "Cosine"
        }
    })
    if status not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — collection setup failed: {status}")
        sys.exit(2)

def check_error_quality(status, body, expected_term):
    """Type-2 diagnosis quality rubric"""
    if body is None:
        return 0, 3
    error_msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()

    score = 0
    if expected_term and expected_term.lower() in error_msg:
        score += 1
    format_hints = ["must be", "expected", "should be", "valid", "type", "array", "object"]
    if any(hint in error_msg for hint in format_hints):
        score += 1
    action_hints = ["correct", "try", "use", "change", "specify"]
    if any(hint in error_msg for hint in action_hints):
        score += 1
    return score, 3

def teardown():
    """Cleanup with try/except per规范"""
    try:
        safe_request("DELETE", f"collections/{COLLECTION}")
    except:
        pass

def main():
    setup_collection()
    time.sleep(0.5)

    # Insert test points with payload
    test_points = [
        {"id": 1, VECTOR_KEY: [0.1]*VECTOR_DIM, "payload": {"category": "A", "score": 10}},
        {"id": 2, VECTOR_KEY: [0.2]*VECTOR_DIM, "payload": {"category": "B", "score": 20}},
        {"id": 3, VECTOR_KEY: [0.3]*VECTOR_DIM, "payload": {"category": "A", "score": 30}},
    ]
    for pt in test_points:
        status, _, raw = safe_request("PUT", f"collections/{COLLECTION}/points", json={POINT_WRAP: [pt]})
        if status not in (200, 201, 204):
            print(f"VERDICT: SCRIPT_ERROR — insert failed: {status}")
            teardown()
            sys.exit(2)

    time.sleep(0.5)

    defects = []

    # Test 1: Empty filter object (should be accepted = no filter)
    status, body, raw = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
        VECTOR_KEY: [0.1]*VECTOR_DIM,
        "limit": 10,
        "filter": {}
    })
    if status != 200:
        defects.append(f"DEFECT_FOUND (Type1_IllegalRejection) — Empty filter object rejected with status {status}")
        score, max_score = check_error_quality(status, body, "filter")
        print(f"Error quality: {score}/{max_score} — raw={raw[:100]}")
    else:
        print(f"INFO: Empty filter accepted")

    # Test 2: Null filter (should be accepted or give clear error)
    status, body, raw = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
        VECTOR_KEY: [0.1]*VECTOR_DIM,
        "limit": 10,
        "filter": None
    })
    if status != 200:
        score, max_score = check_error_quality(status, body, "filter")
        print(f"Error quality for null filter: {score}/{max_score} — raw={raw[:100]}")
        if score <= 1:
            defects.append(f"DEFECT_FOUND (Type2_PoorDiagnostics) — Null filter error lacks details (score {score}/{max_score})")
    else:
        print(f"INFO: Null filter accepted")

    # Test 3: Array instead of object for filter (should be rejected)
    status, body, raw = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
        VECTOR_KEY: [0.1]*VECTOR_DIM,
        "limit": 10,
        "filter": []
    })
    if status == 200:
        defects.append(f"DEFECT_FOUND (Type1_IllegalSuccess) — Array filter silently accepted (should be object)")
    else:
        score, max_score = check_error_quality(status, body, "filter")
        print(f"Error quality for array filter: {score}/{max_score} — raw={raw[:150]}")
        if score <= 1:
            defects.append(f"DEFECT_FOUND (Type2_PoorDiagnostics) — Array filter error lacks details (score {score}/{max_score})")

    # Test 4: Invalid operator in must clause
    status, body, raw = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
        VECTOR_KEY: [0.1]*VECTOR_DIM,
        "limit": 10,
        "filter": {
            "must": [{"invalid_operator": {"category": "A"}}]
        }
    })
    if status == 200:
        print(f"INFO: Invalid operator silently ignored or handled")
    else:
        score, max_score = check_error_quality(status, body, "invalid_operator")
        print(f"Error quality for invalid operator: {score}/{max_score} — raw={raw[:150]}")
        if score <= 1:
            defects.append(f"DEFECT_FOUND (Type2_PoorDiagnostics) — Invalid operator error lacks details (score {score}/{max_score})")

    # Test 5: Type coercion in filter value (string instead of integer for range)
    status, body, raw = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
        VECTOR_KEY: [0.1]*VECTOR_DIM,
        "limit": 10,
        "filter": {
            "must": [{"key": "score", "range": {"gt": "10", "lt": "30"}}]
        }
    })
    if status == 200:
        defects.append(f"DEFECT_FOUND (Type1_IllegalSuccess) — String range values accepted instead of integers")
    else:
        score, max_score = check_error_quality(status, body, "range")
        print(f"Error quality for string range: {score}/{max_score} — raw={raw[:150]}")
        if score <= 1:
            defects.append(f"DEFECT_FOUND (Type2_PoorDiagnostics) — String range error lacks details (score {score}/{max_score})")

    # Test 6: Valid filter with must (should work correctly)
    status, body, raw = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
        VECTOR_KEY: [0.1]*VECTOR_DIM,
        "limit": 10,
        "filter": {
            "must": [{"key": "category", "match": {"value": "A"}}]
        }
    })
    if status == 200:
        if body and "result" in body:
            result_count = len(body["result"])
            if result_count == 2:  # Should return 2 points with category A
                print(f"INFO: Valid filter correctly returned {result_count} results")
            else:
                defects.append(f"DEFECT_FOUND (Type4_StateLogicViolation) — Valid filter returned {result_count} results, expected 2")
        else:
            defects.append(f"DEFECT_FOUND (Type4_StateLogicViolation) — Valid filter response missing result field")
    else:
        defects.append(f"DEFECT_FOUND (Type3_RuntimeFailure) — Valid filter failed with status {status}")

    teardown()

    if defects:
        for d in defects:
            print(d)
        print("VERDICT: DEFECT_FOUND")
        sys.exit(1)
    else:
        print("VERDICT: NO_DEFECT")
        sys.exit(0)

if __name__ == "__main__":
    main()
