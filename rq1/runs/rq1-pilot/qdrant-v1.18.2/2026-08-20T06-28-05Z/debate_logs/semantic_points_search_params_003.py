"""
Attack: params object structure validation
Strategy: diagnosis_quality + illegal_rejection
Endpoint: points+search
Constraint: qdrant_type_search_points_001 (vector dimension match)
Target: qdrant v1.18.2

Tests params object handling:
1. Empty params object {}
2. Null params
3. Invalid param names (typos)
4. Invalid param types (object instead of primitive)
5. Unknown/unsupported params

Blindspot: BS-02 (Error Message Negligence), BS-05 (Documentation Drift)
"""

import os, sys, json, time
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

COLLECTION = "test_search_params_003"
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

def check_error_quality(status, body, expected_param):
    """Type-2 diagnosis quality rubric"""
    if body is None:
        return 0, 3
    error_msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()

    score = 0
    if expected_param and expected_param.lower() in error_msg:
        score += 1
    format_hints = ["must be", "expected", "should be", "valid", "range", "type", "positive"]
    if any(hint in error_msg for hint in format_hints):
        score += 1
    action_hints = ["correct", "try", "use", "change", "specify", "provide"]
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

    # Insert test points
    test_points = [
        {"id": 1, VECTOR_KEY: [0.1]*VECTOR_DIM},
        {"id": 2, VECTOR_KEY: [0.2]*VECTOR_DIM},
    ]
    for pt in test_points:
        status, _, raw = safe_request("PUT", f"collections/{COLLECTION}/points", json={POINT_WRAP: [pt]})
        if status not in (200, 201, 204):
            print(f"VERDICT: SCRIPT_ERROR — insert failed: {status}")
            teardown()
            sys.exit(2)

    time.sleep(0.5)

    defects = []

    # Test 1: Empty params object (should be accepted, uses defaults)
    status, body, raw = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
        VECTOR_KEY: [0.1]*VECTOR_DIM,
        "limit": 10,
        "params": {}
    })
    if status != 200:
        defects.append(f"DEFECT_FOUND (Type1_IllegalRejection) — Empty params object rejected with status {status}")
        score, max_score = check_error_quality(status, body, "params")
        print(f"Error quality: {score}/{max_score} — raw={raw[:100]}")
        if score <= 1:
            defects.append(f"DEFECT_FOUND (Type2_PoorDiagnostics) — Empty params error lacks details (score {score}/{max_score})")
    else:
        print(f"INFO: Empty params accepted")

    # Test 2: Null params (should be accepted or give clear error)
    status, body, raw = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
        VECTOR_KEY: [0.1]*VECTOR_DIM,
        "limit": 10,
        "params": None
    })
    if status != 200:
        score, max_score = check_error_quality(status, body, "params")
        print(f"Error quality for null params: {score}/{max_score} — raw={raw[:100]}")
        if score <= 1:
            defects.append(f"DEFECT_FOUND (Type2_PoorDiagnostics) — Null params error lacks details (score {score}/{max_score})")
    else:
        print(f"INFO: Null params accepted")

    # Test 3: Typo in param name (should be rejected with clear error)
    status, body, raw = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
        VECTOR_KEY: [0.1]*VECTOR_DIM,
        "limit": 10,
        "params": {"hnsw_ef_typo": 100}
    })
    if status == 200:
        defects.append(f"DEFECT_FOUND (Type1_IllegalSuccess) — Typo param 'hnsw_ef_typo' silently ignored")
    else:
        score, max_score = check_error_quality(status, body, "hnsw_ef_typo")
        print(f"Error quality for typo param: {score}/{max_score} — raw={raw[:150]}")
        if score <= 1:
            defects.append(f"DEFECT_FOUND (Type2_PoorDiagnostics) — Typo param error lacks details (score {score}/{max_score})")

    # Test 4: Wrong param type (array instead of object)
    status, body, raw = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
        VECTOR_KEY: [0.1]*VECTOR_DIM,
        "limit": 10,
        "params": [100]
    })
    if status == 200:
        defects.append(f"DEFECT_FOUND (Type1_IllegalSuccess) — Array params silently accepted (should be object)")
    else:
        score, max_score = check_error_quality(status, body, "params")
        print(f"Error quality for array params: {score}/{max_score} — raw={raw[:150]}")
        if score <= 1:
            defects.append(f"DEFECT_FOUND (Type2_PoorDiagnostics) — Array params error lacks details (score {score}/{max_score})")

    # Test 5: Unknown param (should either work with warning or give clear error)
    status, body, raw = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
        VECTOR_KEY: [0.1]*VECTOR_DIM,
        "limit": 10,
        "params": {"unknown_param_xyz": 123}
    })
    if status == 200:
        print(f"INFO: Unknown param 'unknown_param_xyz' silently accepted (may be ignored)")
    else:
        score, max_score = check_error_quality(status, body, "unknown_param_xyz")
        print(f"Error quality for unknown param: {score}/{max_score} — raw={raw[:150]}")
        if score <= 1:
            defects.append(f"DEFECT_FOUND (Type2_PoorDiagnostics) — Unknown param error lacks details (score {score}/{max_score})")

    # Test 6: Invalid nested structure
    status, body, raw = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
        VECTOR_KEY: [0.1]*VECTOR_DIM,
        "limit": 10,
        "params": {"hnsw_ef": {"nested": 100}}
    })
    if status == 200:
        defects.append(f"DEFECT_FOUND (Type1_IllegalSuccess) — Nested object for hnsw_ef silently accepted")
    else:
        score, max_score = check_error_quality(status, body, "hnsw_ef")
        print(f"Error quality for nested hnsw_ef: {score}/{max_score} — raw={raw[:150]}")
        if score <= 1:
            defects.append(f"DEFECT_FOUND (Type2_PoorDiagnostics) — Nested hnsw_ef error lacks details (score {score}/{max_score})")

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
