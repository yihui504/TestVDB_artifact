#!/usr/bin/env python3
"""
Attack: state_consistency
Strategy: upsert_idempotence
Endpoint: /collections/{collection_name}/points:PUT
Constraint: qdrant_state_upsert_points_001
Expected: Type4_StateLogicViolation

Tests upsert idempotence - inserting same point ID twice should count once and last write wins.
Validates that upsert updates rather than duplicates.
"""
import os
import sys
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

COLL_NAME = "test_state_upsert_idempotence"
VECTOR_DIM = 128
POINT_ID = 1

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

def upsert_point(point):
    """Upsert a single point."""
    upsert_body = {
        "points": [point],
        "wait": True
    }
    status, body, raw = safe_request("PUT", f"/collections/{COLL_NAME}/points", json=upsert_body)
    print(f"Upsert point: status={status}, raw={raw[:200]}")
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

def get_point(point_id):
    """Get a specific point by ID."""
    status, body, raw = safe_request("GET", f"/collections/{COLL_NAME}/points/{point_id}")
    print(f"Get point: status={status}, raw={raw[:200]}")
    return status, body

def main():
    cleanup()  # Ensure clean state
    setup_collection()

    # Insert point with ID=1 and vector A
    point_a = {
        "id": POINT_ID,
        "vector": [0.1] * VECTOR_DIM,
        "payload": {"version": "A"}
    }

    status = upsert_point(point_a)
    if status not in [200, 201]:
        print(f"VERDICT: SCRIPT_ERROR — First upsert failed with status {status}")
        cleanup()
        sys.exit(2)

    count_after_first = get_point_count()
    print(f"Count after first upsert: {count_after_first}")

    if count_after_first != 1:
        print(f"VERDICT: SCRIPT_ERROR — Expected 1 point after first upsert, got {count_after_first}")
        cleanup()
        sys.exit(2)

    # Insert same ID=1 with different vector B (should update, not duplicate)
    point_b = {
        "id": POINT_ID,
        "vector": [0.2] * VECTOR_DIM,
        "payload": {"version": "B"}
    }

    status = upsert_point(point_b)
    if status not in [200, 201]:
        print(f"VERDICT: SCRIPT_ERROR — Second upsert failed with status {status}")
        cleanup()
        sys.exit(2)

    count_after_second = get_point_count()
    print(f"Count after second upsert: {count_after_second}")

    # Idempotence check: count should still be 1, not 2
    if count_after_second != 1:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Upsert not idempotent")
        print(f"  Expected count=1 after upserting same ID twice, got count={count_after_second}")
        print(f"  Upsert should update existing point, not insert duplicate")
        cleanup()
        sys.exit(1)

    # Verify last write wins - point should have version B payload
    status, body = get_point(POINT_ID)

    if status == 200 and isinstance(body, dict):
        result = body.get("result")
        if isinstance(result, dict):
            payload = result.get("payload", {})
            if isinstance(payload, dict):
                version = payload.get("version")
                print(f"Point payload version: {version}")
                if version != "B":
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Last write did not win")
                    print(f"  Expected payload version='B', got version='{version}'")
                    print(f"  Upsert should replace existing data with new data")
                    cleanup()
                    sys.exit(1)

    print(f"VERDICT: NO_DEFECT — Upsert is idempotent and last-write-wins satisfied")
    cleanup()
    sys.exit(0)

if __name__ == "__main__":
    main()
