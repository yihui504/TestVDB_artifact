#!/usr/bin/env python3
"""
Attack: delete_consistency
Test: DELETE points → verify search invisibility (deleted points not returned)
Endpoint: points+search
Constraint: qdrant_invariant_delete_invisibility_001, qdrant_behavioral_delete_visibility_001
Source: https://api.qdrant.tech/api-reference/points/search-points
Doc Version: 1.19.x
"""

import os
import sys
import time
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

COLL = "state_search_02"
VECTOR_DIM = 128
NUM_POINTS = 30

def safe_request(method, endpoint, json=None, timeout=10):
    """Safe HTTP request wrapper with unified error handling."""
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.request(method, url, json=json, headers=headers, timeout=timeout)
        status_code = response.status_code
        raw_text = response.text
        try:
            body = response.json()
        except:
            body = raw_text
        return status_code, body, raw_text
    except Exception as e:
        return -1, str(e), str(e)

def setup_collection():
    """Create test collection"""
    create_body = {
        "vectors": {
            "size": VECTOR_DIM,
            "distance": "Cosine"
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{COLL}", json=create_body)
    print(f"Create collection: status={status}")
    return status == 200

def upsert_initial_points():
    """Upsert initial points"""
    points = []
    for i in range(NUM_POINTS):
        points.append({
            "id": i,
            "vector": [0.1] * VECTOR_DIM,
            "payload": {"idx": i}
        })

    status, body, raw = safe_request("PUT", f"/collections/{COLL}/points", json={"points": points})
    print(f"Upsert {NUM_POINTS} points: status={status}")
    return status == 200

def search_for_point(target_id):
    """Search and check if target_id is in results"""
    query_vector = [0.1] * VECTOR_DIM
    search_body = {
        "vector": query_vector,
        "limit": 1000,
        "with_payload": True
    }

    status, body, raw = safe_request("POST", f"/collections/{COLL}/points/search", json=search_body)
    if status != 200:
        return None, f"search failed with status {status}"

    try:
        results = body.get("result", [])
        found_ids = [r.get("id") for r in results]
        return target_id in found_ids, f"search returned {len(results)} results"
    except Exception as e:
        return None, f"parse error: {e}"

def delete_points(point_ids):
    """Delete specific points"""
    delete_body = {
        "points": point_ids,
        "wait": True
    }
    status, body, raw = safe_request("POST", f"/collections/{COLL}/points/delete", json=delete_body)
    print(f"Delete points {point_ids}: status={status}")
    return status == 200

def main():
    # Cleanup existing
    try:
        safe_request("DELETE", f"/collections/{COLL}")
    except:
        pass

    if not setup_collection():
        print("VERDICT: SCRIPT_ERROR — Failed to create collection")
        sys.exit(2)

    time.sleep(0.5)

    if not upsert_initial_points():
        print("VERDICT: SCRIPT_ERROR — Failed to upsert points")
        try:
            safe_request("DELETE", f"/collections/{COLL}")
        except:
            pass
        sys.exit(2)

    time.sleep(1)

    # Verify all points searchable
    for i in range(NUM_POINTS):
        found, msg = search_for_point(i)
        if found is None:
            print(f"VERDICT: SCRIPT_ERROR — Pre-delete search failed: {msg}")
            try:
                safe_request("DELETE", f"/collections/{COLL}")
            except:
                pass
            sys.exit(2)
        if not found:
            print(f"VERDICT: SCRIPT_ERROR — Point {i} not found before delete")
            try:
                safe_request("DELETE", f"/collections/{COLL}")
            except:
                pass
            sys.exit(2)

    # Delete half the points
    to_delete = list(range(0, NUM_POINTS, 2))  # Even IDs
    if not delete_points(to_delete):
        print("VERDICT: SCRIPT_ERROR — Failed to delete points")
        try:
            safe_request("DELETE", f"/collections/{COLL}")
        except:
            pass
        sys.exit(2)

    time.sleep(1)

    # Verify deleted points are NOT searchable
    defect_found = False
    for deleted_id in to_delete:
        found, msg = search_for_point(deleted_id)
        if found is None:
            print(f"VERDICT: SCRIPT_ERROR — Post-delete search failed: {msg}")
            try:
                safe_request("DELETE", f"/collections/{COLL}")
            except:
                pass
            sys.exit(2)
        if found:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Deleted point {deleted_id} still searchable")
            defect_found = True

    # Verify non-deleted points ARE searchable
    for kept_id in range(1, NUM_POINTS, 2):  # Odd IDs
        found, msg = search_for_point(kept_id)
        if found is None:
            print(f"VERDICT: SCRIPT_ERROR — Post-delete search failed for kept point: {msg}")
            try:
                safe_request("DELETE", f"/collections/{COLL}")
            except:
                pass
            sys.exit(2)
        if not found:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Kept point {kept_id} not searchable after delete")
            defect_found = True

    if defect_found:
        try:
            safe_request("DELETE", f"/collections/{COLL}")
        except:
            pass
        sys.exit(1)

    print("VERDICT: NO_DEFECT")

    # Cleanup
    try:
        safe_request("DELETE", f"/collections/{COLL}")
    except Exception:
        pass

if __name__ == "__main__":
    main()
