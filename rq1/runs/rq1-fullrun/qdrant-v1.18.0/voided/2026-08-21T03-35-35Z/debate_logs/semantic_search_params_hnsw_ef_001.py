#!/usr/bin/env python3
"""
Attack: params.hnsw_ef parameter behavior and error quality
Target: Verify hnsw_ef parameter controls search accuracy vs speed
Strategy: diagnosis_quality + behavioral_contract
"""
import os, sys, json, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

def safe_request(method, endpoint, json=None, timeout=10):
    """Safe HTTP request wrapper returning (status, body, raw)"""
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(method, url, json=json, headers=headers, timeout=timeout)
        status = response.status_code
        raw = response.text
        try:
            body = response.json()
        except:
            body = raw
        return status, body, raw
    except Exception as e:
        return -1, str(e), str(e)

COLLECTION = "test_hnsw_ef"
VECTOR_DIM = 128

def setup():
    """Create test collection"""
    try:
        safe_request("DELETE", f"/collections/{COLLECTION}")
    except:
        pass

    status, body, raw = safe_request("PUT", f"/collections/{COLLECTION}", json={
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
        print(f"VERDICT: SCRIPT_ERROR — setup failed: {status}")
        print(raw)
        sys.exit(2)

    # Insert some points
    batch = [{"id": i, "vector": [0.1 * (i % 10)] * VECTOR_DIM} for i in range(100)]
    status, body, raw = safe_request("PUT", f"/collections/{COLLECTION}/points", json={
        "points": batch,
        "wait": True
    })
    if status not in (200, 201, 204):
        print(f"VERDICT: SCRIPT_ERROR — data insert failed: {status}")
        print(raw)
        sys.exit(2)

def teardown():
    """Cleanup test collection"""
    try:
        safe_request("DELETE", f"/collections/{COLLECTION}")
    except Exception:
        pass

def check_error_quality(status, body, raw, expected_param):
    """Type-2 diagnosis quality rubric"""
    error_msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()
    error_msg += " " + raw.lower()

    score = 0
    max_score = 3

    if expected_param.lower() in error_msg or "hnsw" in error_msg or "ef" in error_msg:
        score += 1

    format_hints = ["must be", "expected", "should be", "valid", "range", "type", "positive", "between"]
    if any(hint in error_msg for hint in format_hints):
        score += 1

    action_hints = ["correct", "try", "use", "change", "specify"]
    if any(hint in error_msg for hint in action_hints):
        score += 1

    return score, max_score

def test_hnsw_ef_parameter():
    """
    Test hnsw_ef parameter behavior and error handling.
    Contract: params.hnsw_ef controls search accuracy (higher = more accurate but slower)
    """
    setup()

    # Test 1: Valid hnsw_ef values
    print("\n--- Test 1: Valid hnsw_ef=128 (default range) ---")
    status, body, raw = safe_request("POST", f"/collections/{COLLECTION}/points/search", json={
        "vector": [0.5] * VECTOR_DIM,
        "limit": 10,
        "params": {
            "hnsw_ef": 128
        }
    })
    print(raw)

    if status != 200:
        print(f"VERDICT: SCRIPT_ERROR — search with valid hnsw_ef failed: {status}")
        teardown()
        sys.exit(2)

    # Test 2: Low hnsw_ef (faster but less accurate)
    print("\n--- Test 2: Low hnsw_ef=16 (fast search) ---")
    status, body, raw = safe_request("POST", f"/collections/{COLLECTION}/points/search", json={
        "vector": [0.5] * VECTOR_DIM,
        "limit": 10,
        "params": {
            "hnsw_ef": 16
        }
    })
    print(raw[:500])

    if status != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure)")
        print(f"Low hnsw_ef rejected: {status}")
        teardown()
        sys.exit(1)

    # Test 3: Invalid hnsw_ef (negative)
    print("\n--- Test 3: Invalid hnsw_ef=-1 (negative) ---")
    status, body, raw = safe_request("POST", f"/collections/{COLLECTION}/points/search", json={
        "vector": [0.5] * VECTOR_DIM,
        "limit": 10,
        "params": {
            "hnsw_ef": -1
        }
    })
    print(raw)

    if status == 200:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)")
        print("Negative hnsw_ef should be rejected")
        teardown()
        sys.exit(1)

    score, max_score = check_error_quality(status, body, raw, "hnsw_ef")
    print(f"Error quality: {score}/{max_score}")

    if score < 2:
        print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics)")
        print("Poor error message for invalid hnsw_ef")
        teardown()
        sys.exit(1)

    # Test 4: Invalid hnsw_ef (zero)
    print("\n--- Test 4: Invalid hnsw_ef=0 (zero) ---")
    status, body, raw = safe_request("POST", f"/collections/{COLLECTION}/points/search", json={
        "vector": [0.5] * VECTOR_DIM,
        "limit": 10,
        "params": {
            "hnsw_ef": 0
        }
    })
    print(raw)

    if status == 200:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)")
        print("Zero hnsw_ef should be rejected")
        teardown()
        sys.exit(1)

    # Test 5: Very high hnsw_ef (expensive but should work)
    print("\n--- Test 5: High hnsw_ef=1000 (accurate search) ---")
    status, body, raw = safe_request("POST", f"/collections/{COLLECTION}/points/search", json={
        "vector": [0.5] * VECTOR_DIM,
        "limit": 10,
        "params": {
            "hnsw_ef": 1000
        }
    })
    print(raw[:500])

    if status != 200:
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection)")
        print(f"High hnsw_ef should be accepted but got {status}")
        teardown()
        sys.exit(1)

    print("\nVERDICT: NO_DEFECT")
    teardown()

if __name__ == "__main__":
    test_hnsw_ef_parameter()
