#!/usr/bin/env python3
"""
Attack: count_consistency
Test: CRUD after upsert — verify search results match upserted point count
Endpoint: points+search
Constraint: qdrant_state_search_points_001, qdrant_invariant_search_visibility_001
Source: https://api.qdrant.tech/api-reference/points/search-points
Doc Version: 1.19.x
"""

import os
import sys
import time
import threading
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

COLL = "state_search_01"
VECTOR_DIM = 128
NUM_POINTS = 50

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
    print(f"Create collection: status={status}, raw={raw[:100]}")
    return status == 200

def upsert_points(start_idx, count):
    """Upsert a batch of points"""
    points = []
    for i in range(start_idx, start_idx + count):
        points.append({
            "id": i,
            "vector": [0.1] * VECTOR_DIM,
            "payload": {"batch": start_idx}
        })

    status, body, raw = safe_request("PUT", f"/collections/{COLL}/points", json={"points": points})
    print(f"Upsert batch {start_idx}-{start_idx+count-1}: status={status}")
    return status == 200

def search_and_verify(expected_min):
    """Search and verify result count"""
    query_vector = [0.1] * VECTOR_DIM
    search_body = {
        "vector": query_vector,
        "limit": 1000,
        "with_payload": True
    }

    status, body, raw = safe_request("POST", f"/collections/{COLL}/points/search", json=search_body)
    print(f"Search raw: {raw[:200]}")

    if status != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Search failed with status {status}")
        return False

    try:
        results = body.get("result", [])
        if len(results) < expected_min:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Expected ≥{expected_min} results, got {len(results)}")
            return False
    except Exception as e:
        print(f"VERDICT: SCRIPT_ERROR — Failed to parse search results: {e}")
        return False

    return True

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

    # Insert points in batches
    batch_size = 10
    num_batches = NUM_POINTS // batch_size

    for batch in range(num_batches):
        start_idx = batch * batch_size
        if not upsert_points(start_idx, batch_size):
            print(f"VERDICT: SCRIPT_ERROR — Failed to upsert batch {batch}")
            try:
                safe_request("DELETE", f"/collections/{COLL}")
            except:
                pass
            sys.exit(2)

        time.sleep(0.1)

    time.sleep(1)

    # Verify search returns all points
    if not search_and_verify(NUM_POINTS):
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
