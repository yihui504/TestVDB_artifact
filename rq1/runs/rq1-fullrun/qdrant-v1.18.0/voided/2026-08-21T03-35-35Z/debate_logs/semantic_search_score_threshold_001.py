#!/usr/bin/env python3
"""
Attack: score_threshold parameter semantic correctness
Target: Verify score_threshold correctly filters results
Strategy: search_correctness
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

COLLECTION = "test_score_threshold"
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
        }
    })
    if status not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — setup failed: {status}")
        print(raw)
        sys.exit(2)

def teardown():
    """Cleanup test collection"""
    try:
        safe_request("DELETE", f"/collections/{COLLECTION}")
    except Exception:
        pass

def test_score_threshold_semantics():
    """
    Test that score_threshold correctly filters results.
    High threshold should return fewer/zero results.
    Low threshold should return more results.
    """
    setup()

    # Insert points with varying distances
    query_vector = [0.0] * VECTOR_DIM
    vectors = [
        (2, [0.01] * VECTOR_DIM),
        (3, [0.5] * VECTOR_DIM),
        (4, [0.9] * VECTOR_DIM),
    ]

    for vid, vec in vectors:
        status, body, raw = safe_request("PUT", f"/collections/{COLLECTION}/points", json={
            "points": [{"id": vid, "vector": vec}]
        })
        if status not in (200, 201, 204):
            print(f"VERDICT: SCRIPT_ERROR — insert failed for {vid}: {status}")
            print(raw)
            teardown()
            sys.exit(2)

    # Search with no threshold (should return all)
    print("\n--- Search with score_threshold=0 (default) ---")
    status, body, raw = safe_request("POST", f"/collections/{COLLECTION}/points/search", json={
        "vector": query_vector,
        "limit": 10,
        "score_threshold": 0.0
    })
    print(raw)

    if status != 200:
        print(f"VERDICT: SCRIPT_ERROR — search failed: {status}")
        teardown()
        sys.exit(2)

    results = body.get("result") if isinstance(body, dict) else None
    count_no_threshold = len(results) if results and hasattr(results, '__len__') else 0
    print(f"Results with threshold=0.0: {count_no_threshold}")

    # Search with high threshold (should return fewer or zero)
    print("\n--- Search with score_threshold=0.99 ---")
    status, body, raw = safe_request("POST", f"/collections/{COLLECTION}/points/search", json={
        "vector": query_vector,
        "limit": 10,
        "score_threshold": 0.99
    })
    print(raw)

    if status != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure)")
        print(f"Search with high threshold failed: {status}")
        teardown()
        sys.exit(1)

    results = body.get("result") if isinstance(body, dict) else None
    count_high_threshold = len(results) if results and hasattr(results, '__len__') else 0
    print(f"Results with threshold=0.99: {count_high_threshold}")

    # Semantic contract: Higher threshold should return <= results of lower threshold
    if count_high_threshold > count_no_threshold:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"High threshold (0.99) returned {count_high_threshold} > {count_no_threshold} (threshold 0.0)")
        print("score_threshold failed to filter correctly")
        teardown()
        sys.exit(1)

    # Test with extremely high threshold (should return 0)
    print("\n--- Search with score_threshold=1.5 (impossible) ---")
    status, body, raw = safe_request("POST", f"/collections/{COLLECTION}/points/search", json={
        "vector": query_vector,
        "limit": 10,
        "score_threshold": 1.5
    })
    print(raw)

    if status != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure)")
        print(f"Search with impossible threshold failed: {status}")
        teardown()
        sys.exit(1)

    results = body.get("result") if isinstance(body, dict) else None
    count_impossible = len(results) if results and hasattr(results, '__len__') else 0

    if count_impossible != 0:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"Impossible threshold (1.5) returned {count_impossible} results, expected 0")
        teardown()
        sys.exit(1)

    print("VERDICT: NO_DEFECT")
    teardown()

if __name__ == "__main__":
    test_score_threshold_semantics()
