"""
Attack: hnsw_ef range validation and behavioral contract
Strategy: behavioral_contract + diagnosis_quality
Endpoint: points+search
Constraint: qdrant_range_create_collection_002 (ef_construct ∈ [10, 1000])
Target: qdrant v1.18.2

Tests hnsw_ef parameter behavior:
1. Range validation (if any constraints exist)
2. Search result consistency with different hnsw_ef values
3. Default value handling when params omitted

Behavioral contract: hnsw_ef controls search speed/accuracy tradeoff.
Higher ef = slower but more accurate results.

Blindspot: BS-02 (Error Message Negligence)
"""

import os, sys, json, time
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

COLLECTION = "test_search_hnsw_ef_002"
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

    # Insert test points with different distances
    test_points = [
        {"id": 1, VECTOR_KEY: [0.0]*VECTOR_DIM},  # Exact match
        {"id": 2, VECTOR_KEY: [0.01]*VECTOR_DIM},  # Very close
        {"id": 3, VECTOR_KEY: [0.1]*VECTOR_DIM},   # Close
        {"id": 4, VECTOR_KEY: [0.5]*VECTOR_DIM},   # Medium
        {"id": 5, VECTOR_KEY: [1.0]*VECTOR_DIM},   # Far
    ]
    for pt in test_points:
        status, _, raw = safe_request("PUT", f"collections/{COLLECTION}/points", json={POINT_WRAP: [pt]})
        if status not in (200, 201, 204):
            print(f"VERDICT: SCRIPT_ERROR — insert failed: {status}")
            teardown()
            sys.exit(2)

    time.sleep(0.5)

    defects = []

    # Test 1: Extremely large hnsw_ef (should either work or give clear error)
    status, body, raw = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
        VECTOR_KEY: [0.0]*VECTOR_DIM,
        "limit": 5,
        "params": {"hnsw_ef": 1000000}
    })
    if status != 200:
        score, max_score = check_error_quality(status, body, "hnsw_ef")
        print(f"Error quality for hnsw_ef=1000000: {score}/{max_score} — raw={raw[:150]}")
        if score <= 1:
            defects.append(f"DEFECT_FOUND (Type2_PoorDiagnostics) — Large hnsw_ef error lacks details (score {score}/{max_score})")
    else:
        # If accepted, verify it returns results (Type-4)
        if body and "result" in body and len(body["result"]) > 0:
            print(f"INFO: Large hnsw_ef=1000000 accepted and returns {len(body['result'])} results")
        else:
            defects.append(f"DEFECT_FOUND (Type4_StateLogicViolation) — Large hnsw_ef accepted but returned no results")

    # Test 2: Small hnsw_ef value (edge case)
    status, body, raw = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
        VECTOR_KEY: [0.0]*VECTOR_DIM,
        "limit": 5,
        "params": {"hnsw_ef": 1}
    })
    if status != 200:
        score, max_score = check_error_quality(status, body, "hnsw_ef")
        print(f"Error quality for hnsw_ef=1: {score}/{max_score} — raw={raw[:150]}")
        if score <= 1:
            defects.append(f"DEFECT_FOUND (Type2_PoorDiagnostics) — Small hnsw_ef error lacks details (score {score}/{max_score})")
    else:
        # If accepted, verify it returns results (Type-4)
        if body and "result" in body and len(body["result"]) > 0:
            print(f"INFO: Small hnsw_ef=1 accepted and returns {len(body['result'])} results")
        else:
            defects.append(f"DEFECT_FOUND (Type4_StateLogicViolation) — Small hnsw_ef accepted but returned no results")

    # Test 3: Behavioral contract - same query with different hnsw_ef should give similar top results
    query_vec = [0.0]*VECTOR_DIM

    status1, body1, raw1 = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
        VECTOR_KEY: query_vec,
        "limit": 3,
        "params": {"hnsw_ef": 10}
    })

    status2, body2, raw2 = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
        VECTOR_KEY: query_vec,
        "limit": 3,
        "params": {"hnsw_ef": 100}
    })

    if status1 == 200 and status2 == 200:
        if body1 and "result" in body1 and body2 and "result" in body2:
            ids1 = [r.get("id") for r in body1["result"][:3]]
            ids2 = [r.get("id") for r in body2["result"][:3]]
            print(f"Top 3 IDs with ef=10: {ids1}")
            print(f"Top 3 IDs with ef=100: {ids2}")

            # First result should always be the same (id=1, exact match)
            if ids1[0] != ids2[0]:
                defects.append(f"DEFECT_FOUND (Type4_StateLogicViolation) — Different hnsw_ef gave different top result: {ids1[0]} vs {ids2[0]}")
            elif ids1[0] != 1:
                defects.append(f"DEFECT_FOUND (Type4_StateLogicViolation) — Top result should be id=1 (exact match), got {ids1[0]}")
        else:
            defects.append(f"DEFECT_FOUND (Type4_StateLogicViolation) — Search responses missing result field")
    else:
        print(f"INFO: Behavioral test skipped due to errors: {status1}, {status2}")

    # Test 4: Omit params entirely (should use default)
    status, body, raw = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
        VECTOR_KEY: query_vec,
        "limit": 3
    })
    if status == 200:
        if body and "result" in body and len(body["result"]) > 0:
            print(f"INFO: Omitted params uses default, returns {len(body['result'])} results")
        else:
            defects.append(f"DEFECT_FOUND (Type4_StateLogicViolation) — Omitted params returns no results")
    else:
        defects.append(f"DEFECT_FOUND (Type3_RuntimeFailure) — Omitted params caused error")

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
