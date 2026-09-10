#!/usr/bin/env python3
"""
Attack: state_consistency
Strategy: count_consistency
Endpoint: /collections/{collection_name}/points:PUT
Constraint: qdrant_state_upsert_points_001
Expected: Type4_StateLogicViolation

Tests upsert atomicity - batch insert should increase count by exact number of points.
Validates state_invariant: qdrant_invariant_upsert_count_001
"""
import os
import sys
import time
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

COLL_NAME = "test_state_upsert_001"
VECTOR_DIM = 128
NUM_POINTS = 10

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

def get_point_count():
    """Get current point count via scroll."""
    scroll_body = {"limit": 1000}
    status, body, raw = safe_request("POST", f"/collections/{COLL_NAME}/points/scroll", json=scroll_body)
    print(f"Scroll: status={status}, raw={raw[:200]}")

    if status == 200 and isinstance(body, dict):
        # Qdrant returns result with data array
        points = body.get("result", {}).get("data", [])
        if isinstance(points, list):
            return len(points)
    return 0

def upsert_points(points):
    """Upsert points with wait=true for synchronous behavior."""
    upsert_body = {
        "points": points,
        "wait": True
    }
    status, body, raw = safe_request("PUT", f"/collections/{COLL_NAME}/points", json=upsert_body)
    print(f"Upsert: status={status}, raw={raw[:200]}")
    return status

def main():
    cleanup()  # Ensure clean state
    setup_collection()

    count_before = get_point_count()
    print(f"Count before upsert: {count_before}")

    # Generate test points
    points = []
    for i in range(NUM_POINTS):
        points.append({
            "id": i,
            "vector": [0.1] * VECTOR_DIM
        })

    # Upsert points
    status = upsert_points(points)
    if status not in [200, 201]:
        print(f"VERDICT: SCRIPT_ERROR — Upsert failed with status {status}")
        cleanup()
        sys.exit(2)

    # Small delay for any eventual consistency
    time.sleep(0.5)

    count_after = get_point_count()
    print(f"Count after upsert: {count_after}")

    expected = count_before + NUM_POINTS
    if count_after != expected:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Expected {expected} points, got {count_after}")
        print(f"  State invariant violation: upsert should increase count by {NUM_POINTS}")
        cleanup()
        sys.exit(1)

    print(f"VERDICT: NO_DEFECT — Count invariant satisfied: {count_after} == {expected}")
    cleanup()
    sys.exit(0)

if __name__ == "__main__":
    main()
