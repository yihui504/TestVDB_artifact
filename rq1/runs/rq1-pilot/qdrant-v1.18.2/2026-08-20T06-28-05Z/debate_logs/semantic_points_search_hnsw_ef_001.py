"""
Attack: hnsw_ef parameter type coercion and diagnostics quality
Strategy: type_coercion + diagnosis_quality
Endpoint: points+search
Constraint: qdrant_type_search_points_001 (vector dimension match)
Target: qdrant v1.18.2

Tests hnsw_ef parameter inside nested params object for:
1. Type coercion (string/int/float confusion)
2. Error message quality when invalid
3. Range validation (if any)

Blindspot: BS-02 (Error Message Negligence), BS-05 (Documentation Drift)
"""

import os, sys, json, time
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

COLLECTION = "test_search_hnsw_ef_001"
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
    """Create test collection with HNSW config"""
    status, body, raw = safe_request("PUT", "collections/" + COLLECTION, json={
        "vectors": {
            "size": VECTOR_DIM,
            "distance": "Cosine"
        },
        "hnsw_config": {
            "m": 16,
            "ef_construct": 100
        }
    })
    if status not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — collection setup failed: {status}")
        sys.exit(2)

def check_error_quality(status, body, expected_param):
    """
    Type-2 diagnosis quality rubric:
    - Must mention the parameter name
    - Should indicate correct format
    - Bonus: actionable suggestion
    """
    if body is None:
        return 0, 3
    error_msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()

    score = 0
    max_score = 3

    # Criterion 1: Parameter named
    if expected_param and expected_param.lower() in error_msg:
        score += 1

    # Criterion 2: Format/range hint
    format_hints = ["must be", "expected", "should be", "valid", "range", "type", "positive", "integer"]
    if any(hint in error_msg for hint in format_hints):
        score += 1

    # Criterion 3: Actionable suggestion
    action_hints = ["correct", "try", "use", "change", "specify", "provide"]
    if any(hint in error_msg for hint in action_hints):
        score += 1

    return score, max_score

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

    # Test 1: String "100" instead of integer 100 for hnsw_ef (Type-1 illegal success if accepted)
    status, body, raw = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
        VECTOR_KEY: [0.1]*VECTOR_DIM,
        "limit": 10,
        "params": {"hnsw_ef": "100"}
    })
    if status == 200:
        defects.append(f"DEFECT_FOUND (Type1_IllegalSuccess) — String '100' accepted as hnsw_ef integer")

    # Test 2: Float 100.5 instead of integer 100
    status, body, raw = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
        VECTOR_KEY: [0.1]*VECTOR_DIM,
        "limit": 10,
        "params": {"hnsw_ef": 100.5}
    })
    if status == 200:
        defects.append(f"DEFECT_FOUND (Type1_IllegalSuccess) — Float 100.5 accepted as hnsw_ef integer")

    # Test 3: Boolean true instead of integer
    status, body, raw = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
        VECTOR_KEY: [0.1]*VECTOR_DIM,
        "limit": 10,
        "params": {"hnsw_ef": True}
    })
    if status == 200:
        defects.append(f"DEFECT_FOUND (Type1_IllegalSuccess) — Boolean true accepted as hnsw_ef integer")

    # Test 4: Negative value (should be rejected with clear error)
    status, body, raw = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
        VECTOR_KEY: [0.1]*VECTOR_DIM,
        "limit": 10,
        "params": {"hnsw_ef": -10}
    })
    if status != 200:
        score, max_score = check_error_quality(status, body, "hnsw_ef")
        print(f"Error quality for negative hnsw_ef: {score}/{max_score} — raw={raw[:100]}")
        if score <= 1:
            defects.append(f"DEFECT_FOUND (Type2_PoorDiagnostics) — Negative hnsw_ef error lacks details (score {score}/{max_score})")
    else:
        defects.append(f"DEFECT_FOUND (Type1_IllegalSuccess) — Negative hnsw_ef=-10 accepted")

    # Test 5: Zero value
    status, body, raw = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
        VECTOR_KEY: [0.1]*VECTOR_DIM,
        "limit": 10,
        "params": {"hnsw_ef": 0}
    })
    if status != 200:
        score, max_score = check_error_quality(status, body, "hnsw_ef")
        print(f"Error quality for hnsw_ef=0: {score}/{max_score} — raw={raw[:100]}")
        if score <= 1:
            defects.append(f"DEFECT_FOUND (Type2_PoorDiagnostics) — Zero hnsw_ef error lacks details (score {score}/{max_score})")
    else:
        defects.append(f"DEFECT_FOUND (Type1_IllegalSuccess) — Zero hnsw_ef=0 accepted")

    # Test 6: Null value
    status, body, raw = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
        VECTOR_KEY: [0.1]*VECTOR_DIM,
        "limit": 10,
        "params": {"hnsw_ef": None}
    })
    if status != 200:
        score, max_score = check_error_quality(status, body, "hnsw_ef")
        print(f"Error quality for hnsw_ef=null: {score}/{max_score} — raw={raw[:100]}")
        if score <= 1:
            defects.append(f"DEFECT_FOUND (Type2_PoorDiagnostics) — Null hnsw_ef error lacks details (score {score}/{max_score})")
    else:
        # Might be acceptable (null means use default)
        print(f"INFO: Null hnsw_ef accepted (uses default)")

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
