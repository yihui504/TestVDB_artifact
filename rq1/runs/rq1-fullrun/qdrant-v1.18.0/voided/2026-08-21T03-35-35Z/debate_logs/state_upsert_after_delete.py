#!/usr/bin/env python3
"""
Attack: state_consistency
Strategy: sequence_consistency
Endpoint: /collections/{collection_name}/points:PUT
Constraint: qdrant_state_upsert_points_001
Expected: Type4_StateLogicViolation

Tests upsert after delete - operations should maintain consistent state after delete+recreate cycle.
Validates that delete removes all points and subsequent upserts start from zero count.
"""
import os
import sys
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

COLL_NAME = "test_state_upsert_after_delete"
VECTOR_DIM = 128

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

def upsert_points(points):
    """Upsert points."""
    upsert_body = {
        "points": points,
        "wait": True
    }
    status, body, raw = safe_request("PUT", f"/collections/{COLL_NAME}/points", json=upsert_body)
    print(f"Upsert points: status={status}, raw={raw[:200]}")
    return status

def delete_points(point_ids):
    """Delete specific points."""
    delete_body = {
        "points": point_ids,
        "wait": True
    }
    status, body, raw = safe_request("POST", f"/collections/{COLL_NAME}/points/delete", json=delete_body)
    print(f"Delete points: status={status}, raw={raw[:200]}")
    return status

def get_point_count():
    """Get current point count via scroll."""
    scroll_body = {"limit": 1000}
    status, body, raw = safe_request("POST", f"/collections/{COLL_NAME}/points/scroll", json=scroll_body)
    print(f"Scroll: status={status}, raw={raw[:200]}")

    if status == 200 and isinstance(body, dict):
        points = body.get("result", {}).get("points", [])
        if isinstance(points, list):
            return len(points)
    return 0

def main():
    cleanup()  # Ensure clean state
    setup_collection()

    # Phase 1: Upsert 10 points
    points = [{"id": i, "vector": [0.1] * VECTOR_DIM} for i in range(10)]
    status = upsert_points(points)
    if status not in [200, 201]:
        print(f"VERDICT: SCRIPT_ERROR — First upsert failed")
        cleanup()
        sys.exit(2)

    count_phase1 = get_point_count()
    print(f"Count after phase 1 (10 upserts): {count_phase1}")

    if count_phase1 != 10:
        print(f"VERDICT: SCRIPT_ERROR — Expected 10 points, got {count_phase1}")
        cleanup()
        sys.exit(2)

    # Phase 2: Delete 5 points
    ids_to_delete = list(range(5))
    status = delete_points(ids_to_delete)
    if status not in [200, 204]:
        print(f"VERDICT: SCRIPT_ERROR — Delete failed")
        cleanup()
        sys.exit(2)

    count_phase2 = get_point_count()
    print(f"Count after phase 2 (deleted 5): {count_phase2}")

    if count_phase2 != 5:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Delete state inconsistent")
        print(f"  Expected 5 points after deleting 5 from 10, got {count_phase2}")
        cleanup()
        sys.exit(1)

    # Phase 3: Upsert 3 new points (IDs 10-12, different from deleted 0-4)
    new_points = [{"id": i + 10, "vector": [0.2] * VECTOR_DIM} for i in range(3)]
    status = upsert_points(new_points)
    if status not in [200, 201]:
        print(f"VERDICT: SCRIPT_ERROR — Second upsert failed")
        cleanup()
        sys.exit(2)

    count_phase3 = get_point_count()
    print(f"Count after phase 3 (upsert 3 new): {count_phase3}")

    # Should have 5 remaining + 3 new = 8 total
    if count_phase3 != 8:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Upsert after delete state inconsistent")
        print(f"  Expected 8 points (5 remaining + 3 new), got {count_phase3}")
        print(f"  Delete + upsert sequence should maintain consistent count")
        cleanup()
        sys.exit(1)

    print(f"VERDICT: NO_DEFECT — Delete + upsert sequence maintains consistent state")
    cleanup()
    sys.exit(0)

if __name__ == "__main__":
    main()
