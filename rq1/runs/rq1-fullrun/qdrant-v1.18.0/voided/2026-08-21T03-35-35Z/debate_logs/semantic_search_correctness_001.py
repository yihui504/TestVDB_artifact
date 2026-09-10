#!/usr/bin/env python3
"""
Attack: qdrant_behavioral_search_points_001 - Search semantic correctness
Target: Verify search returns correct nearest neighbors by distance
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

COLLECTION = "test_search_correctness"
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

def test_search_semantic_correctness():
    """
    Verify search returns correct nearest neighbors by distance.
    Contract qdrant_behavioral_search_points_001: returns 200 OK with scored results
    """
    setup()

    # Insert points with known distances to query
    query_vector = [0.0] * VECTOR_DIM

    # Points with increasing distance from query
    vectors = [
        (1, query_vector),  # Distance 0
        (2, [0.01] * VECTOR_DIM),  # Very close
        (3, [0.1] * VECTOR_DIM),  # Medium
        (4, [1.0] * VECTOR_DIM),  # Far
        (5, [10.0] * VECTOR_DIM),  # Very far
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

    # Search with query
    status, body, raw = safe_request("POST", f"/collections/{COLLECTION}/points/search", json={
        "vector": query_vector,
        "limit": 5
    })

    print(raw)

    if status != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure)")
        print(f"Search failed with status {status}")
        teardown()
        sys.exit(1)

    # Extract results from Qdrant response
    results = body.get("result") if isinstance(body, dict) else None

    if results is None or not hasattr(results, '__len__'):
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"Expected results array, got: {results}")
        teardown()
        sys.exit(1)

    if len(results) == 0:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print("Search returned empty results for non-empty collection")
        teardown()
        sys.exit(1)

    # Verify ordering: closest should be first
    result_ids = []
    for r in results:
        if isinstance(r, dict):
            result_ids.append(r.get("id"))

    print(f"Result order: {result_ids}")

    # 1 should be first (distance 0)
    if len(results) > 0 and result_ids[0] != 1:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"Expected 1 first (closest), got '{result_ids[0]}'")
        print("Semantic correctness violation: nearest neighbor not returned first")
        teardown()
        sys.exit(1)

    # Verify results are in distance order (decreasing similarity)
    expected_order = [1, 2, 3, 4, 5]
    # Allow some flexibility but top 3 should be exact, close, medium
    if len(results) >= 3:
        top3 = result_ids[:3]
        if 1 not in top3 or 2 not in top3[:2]:
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"Top results not in distance order: {top3}")
            print("Expected closest points first")
            teardown()
            sys.exit(1)

    print("VERDICT: NO_DEFECT")
    teardown()

if __name__ == "__main__":
    test_search_semantic_correctness()
