#!/usr/bin/env python3
"""
Attack: state_consistency
Strategy: upsert_search_visibility
Endpoint: /collections/{collection_name}/points:PUT
Constraint: qdrant_state_upsert_points_001
Expected: Type4_StateLogicViolation

Tests wait parameter semantics - upsert with wait=true should make points immediately searchable.
Validates that upserted data is visible to search without additional delays.
"""
import os
import sys
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

COLL_NAME = "test_state_upsert_wait"
VECTOR_DIM = 128
NUM_POINTS = 5

def safe_request(method, endpoint, json=None, timeout=10):
    """Safe HTTP request wrapper with unified error handling."""
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.request(
            method=method,
            url=url,
            json=json,
            headers=headers,
            timeout=timeout
        )
        status_code = response.status_code
        raw_text = response.text

        try:
            body = response.json()
        except:
            body = raw_text

        return status_code, body, raw_text
    except Exception as e:
        return -1, str(e), str(e)

def cleanup():
    """Remove test collection."""
    try:
        safe_request("DELETE", f"/collections/{COLL_NAME}")
    except Exception:
        pass

def setup_collection():
    """Create test collection."""
    create_body = {
        "vectors": {
            "size": VECTOR_DIM,
            "distance": "Cosine"
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{COLL_NAME}", json=create_body)
    print(f"Create collection: status={status}, raw={raw[:200]}")
    if status not in [200, 201]:
        print(f"VERDICT: SCRIPT_ERROR — Failed to create collection")
        sys.exit(2)

def upsert_with_wait(points):
    """Upsert with wait=true for synchronous visibility."""
    upsert_body = {
        "points": points,
        "wait": True
    }
    status, body, raw = safe_request("PUT", f"/collections/{COLL_NAME}/points", json=upsert_body)
    print(f"Upsert with wait: status={status}, raw={raw[:200]}")
    return status

def search_points(query_vector, limit=10):
    """Search for similar points."""
    search_body = {
        "vector": query_vector,
        "limit": limit
    }
    status, body, raw = safe_request("POST", f"/collections/{COLL_NAME}/points/search", json=search_body)
    print(f"Search: status={status}, raw={raw[:200]}")

    if status == 200 and isinstance(body, dict):
        results = body.get("result", [])
        if isinstance(results, list):
            return results
    return []

def main():
    cleanup()  # Ensure clean state
    setup_collection()

    # Create test points with unique vectors
    points = []
    for i in range(NUM_POINTS):
        points.append({
            "id": i,
            "vector": [0.1 * (i + 1)] * VECTOR_DIM
        })

    # Upsert with wait=true
    status = upsert_with_wait(points)
    if status not in [200, 201]:
        print(f"VERDICT: SCRIPT_ERROR — Upsert failed with status {status}")
        cleanup()
        sys.exit(2)

    # Immediately search - should find all points with wait=true
    query_vector = [0.1] * VECTOR_DIM  # Same as first point
    results = search_points(query_vector, limit=NUM_POINTS)

    print(f"Search results count: {len(results)}")

    # With wait=true, upserted points should be immediately visible
    if len(results) < NUM_POINTS:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — wait=true semantics violated")
        print(f"  Expected {NUM_POINTS} points visible, got {len(results)}")
        print(f"  wait=true should guarantee immediate search visibility")
        cleanup()
        sys.exit(1)

    # Verify all upserted IDs are present
    found_ids = set()
    for result in results:
        if isinstance(result, dict):
            point_id = result.get("id")
            if point_id is not None:
                found_ids.add(point_id)

    print(f"Found IDs: {sorted(found_ids)}")
    expected_ids = set(range(NUM_POINTS))

    if found_ids != expected_ids:
        missing = expected_ids - found_ids
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Missing point IDs: {missing}")
        print(f"  wait=true should ensure all points are indexed and searchable")
        cleanup()
        sys.exit(1)

    print(f"VERDICT: NO_DEFECT — wait=true semantics satisfied, all {NUM_POINTS} points visible")
    cleanup()
    sys.exit(0)

if __name__ == "__main__":
    main()
