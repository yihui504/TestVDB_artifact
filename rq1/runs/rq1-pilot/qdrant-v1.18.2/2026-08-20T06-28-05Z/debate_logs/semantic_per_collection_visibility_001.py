"""
Attack: Per-collection state invariant violations
Strategy: behavioral_contract
Endpoint: per_collection (multi-endpoint sequences)
Constraint: qdrant_invariant_search_visibility_001, qdrant_invariant_count_consistency_001
Target: qdrant v1.18.2

Tests state invariants:
1. Upserted points should be visible in search (invariant qdrant_invariant_search_visibility_001)
2. Inserting N points should result in scroll returning N points (invariant qdrant_invariant_count_consistency_001)
3. Deleted points should not be visible in search (invariant qdrant_invariant_delete_invisibility_001)

Blindspot: BS-02 (Error Message Negligence)
"""

import os, sys, json, time
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

COLLECTION = "test_per_collection_visibility"
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

def teardown():
    """Cleanup with try/except per规范"""
    try:
        safe_request("DELETE", f"collections/{COLLECTION}")
    except:
        pass

def main():
    setup_collection()
    time.sleep(0.5)

    defects = []

    # Test 1: Invariant qdrant_invariant_search_visibility_001
    # Upsert points and verify they're immediately visible in search
    test_points = [
        {"id": 101, VECTOR_KEY: [0.1]*VECTOR_DIM},
        {"id": 102, VECTOR_KEY: [0.2]*VECTOR_DIM},
        {"id": 103, VECTOR_KEY: [0.3]*VECTOR_DIM},
    ]
    for pt in test_points:
        status, _, raw = safe_request("PUT", f"collections/{COLLECTION}/points", json={POINT_WRAP: [pt]})
        if status not in (200, 201, 204):
            print(f"VERDICT: SCRIPT_ERROR — insert failed: {status}")
            teardown()
            sys.exit(2)

    time.sleep(0.3)  # Give index time to update

    # Search should return these points
    status, body, raw = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
        VECTOR_KEY: [0.1]*VECTOR_DIM,
        "limit": 10
    })
    if status != 200:
        defects.append(f"DEFECT_FOUND (Type3_RuntimeFailure) — Search failed after upsert: status={status}")
    else:
        if body and "result" in body:
            result_count = len(body["result"])
            if result_count == 0:
                defects.append(f"DEFECT_FOUND (Type4_StateLogicViolation) — Invariant violated: upserted points not visible in search")
            else:
                print(f"INFO: Search returned {result_count} points after upsert (expected >= 1)")
                # Verify ID 101 is in results
                found_ids = [r.get("id") for r in body["result"]]
                if 101 not in found_ids:
                    defects.append(f"DEFECT_FOUND (Type4_StateLogicViolation) — Invariant violated: upserted point ID 101 not in search results")
        else:
            defects.append(f"DEFECT_FOUND (Type4_StateLogicViolation) — Search response missing result field")

    # Test 2: Invariant qdrant_invariant_count_consistency_001
    # Insert exactly 5 points, scroll should return 5
    count_test_points = [
        {"id": 201, VECTOR_KEY: [0.4]*VECTOR_DIM},
        {"id": 202, VECTOR_KEY: [0.5]*VECTOR_DIM},
        {"id": 203, VECTOR_KEY: [0.6]*VECTOR_DIM},
        {"id": 204, VECTOR_KEY: [0.7]*VECTOR_DIM},
        {"id": 205, VECTOR_KEY: [0.8]*VECTOR_DIM},
    ]
    for pt in count_test_points:
        status, _, raw = safe_request("PUT", f"collections/{COLLECTION}/points", json={POINT_WRAP: [pt]})
        if status not in (200, 201, 204):
            print(f"VERDICT: SCRIPT_ERROR — count test insert failed: {status}")
            teardown()
            sys.exit(2)

    time.sleep(0.3)

    # Scroll should return all points
    all_points = []
    offset = None
    while True:
        scroll_payload = {"limit": 10}
        if offset is not None:
            scroll_payload["offset"] = offset

        status, body, raw = safe_request("POST", f"collections/{COLLECTION}/points/scroll", json=scroll_payload)
        if status != 200:
            defects.append(f"DEFECT_FOUND (Type3_RuntimeFailure) — Scroll failed: status={status}")
            break

        if body and "result" in body and "points" in body["result"]:
            batch = body["result"]["points"]
            all_points.extend(batch)
            if len(batch) == 0 or body["result"].get("is_end", False):
                break
            offset = batch[-1].get("id")
        else:
            defects.append(f"DEFECT_FOUND (Type4_StateLogicViolation) — Scroll response missing expected fields")
            break

    total_inserted = len(test_points) + len(count_test_points)
    if len(all_points) != total_inserted:
        defects.append(f"DEFECT_FOUND (Type4_StateLogicViolation) — Invariant violated: inserted {total_inserted} points but scroll returned {len(all_points)}")
    else:
        print(f"INFO: Count consistency invariant holds: {len(all_points)} points")

    # Test 3: Invariant qdrant_invariant_delete_invisibility_001
    # Delete a point and verify it's not in search results
    delete_id = 102
    status, _, raw = safe_request("POST", f"collections/{COLLECTION}/points/delete", json={
        "points": [delete_id]
    })
    if status not in (200, 204):
        defects.append(f"DEFECT_FOUND (Type3_RuntimeFailure) — Delete failed: status={status}")
    else:
        time.sleep(0.3)
        # Search should NOT return the deleted point
        status, body, raw = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
            VECTOR_KEY: [0.2]*VECTOR_DIM,
            "limit": 10
        })
        if status == 200 and body and "result" in body:
            found_ids = [r.get("id") for r in body["result"]]
            if delete_id in found_ids:
                defects.append(f"DEFECT_FOUND (Type4_StateLogicViolation) — Invariant violated: deleted point {delete_id} still visible in search")
            else:
                print(f"INFO: Delete invariant holds: deleted point {delete_id} not in search results")
        else:
            defects.append(f"DEFECT_FOUND (Type4_StateLogicViolation) — Search after delete failed")

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
