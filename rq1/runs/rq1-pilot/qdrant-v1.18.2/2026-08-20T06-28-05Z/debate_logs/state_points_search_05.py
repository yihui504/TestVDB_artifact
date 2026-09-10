#!/usr/bin/env python3
"""
Attack: concurrent
Test: Concurrent delete+search — verify deleted points invisible during search
Endpoint: points+search
Constraint: qdrant_invariant_delete_invisibility_001, qdrant_state_upsert_points_001
Source: https://api.qdrant.tech/api-reference/points/search-points
Doc Version: 1.19.x
"""

import os
import sys
import time
import threading
import requests
from collections import defaultdict

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

COLL = "state_search_05"
VECTOR_DIM = 128
NUM_POINTS = 100
NUM_THREADS = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "20"))

thread_errors = []
deleted_visibility = []
lock = threading.Lock()

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

def delete_worker(thread_id, points_to_delete):
    """Worker that deletes points"""
    chunk_size = len(points_to_delete) // (NUM_THREADS // 2)
    start_idx = thread_id * chunk_size
    end_idx = start_idx + chunk_size if thread_id < (NUM_THREADS // 2) - 1 else len(points_to_delete)

    for idx in range(start_idx, end_idx):
        point_id = points_to_delete[idx]
        delete_body = {
            "points": [point_id],
            "wait": True
        }

        status, body, raw = safe_request("POST", f"/collections/{COLL}/points/delete", json=delete_body)
        if status != 200:
            with lock:
                thread_errors.append(f"delete thread {thread_id} point {point_id}: status {status}")

        time.sleep(0.01)

def search_worker(thread_id, deleted_ids):
    """Worker that searches and checks for deleted points"""
    for _ in range(5):
        query_vector = [0.1] * VECTOR_DIM
        search_body = {
            "vector": query_vector,
            "limit": 1000,
            "with_payload": True
        }

        status, body, raw = safe_request("POST", f"/collections/{COLL}/points/search", json=search_body)

        if status == 200:
            try:
                results = body.get("result", [])
                found_ids = [r.get("id") for r in results]

                # Check if any deleted IDs are still visible
                for deleted_id in deleted_ids:
                    if deleted_id in found_ids:
                        with lock:
                            deleted_visibility.append(deleted_id)
                        break
            except Exception as e:
                with lock:
                    thread_errors.append(f"search thread {thread_id}: parse error {e}")
        else:
            with lock:
                thread_errors.append(f"search thread {thread_id}: status {status}")

        time.sleep(0.02)

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

    # Select points to delete (first half)
    points_to_delete = list(range(NUM_POINTS // 2))

    # Launch concurrent delete and search threads
    threads = []

    # Start delete threads
    for t in range(NUM_THREADS // 2):
        thr = threading.Thread(target=delete_worker, args=(t, points_to_delete))
        threads.append(thr)
        thr.start()

    # Start search threads
    for t in range(NUM_THREADS // 2):
        thr = threading.Thread(target=search_worker, args=(t, points_to_delete))
        threads.append(thr)
        thr.start()

    # Wait for completion
    for thr in threads:
        thr.join()

    time.sleep(2)

    # Check for errors during execution
    if thread_errors:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Concurrent errors: {thread_errors[:5]}")
        try:
            safe_request("DELETE", f"/collections/{COLL}")
        except:
            pass
        sys.exit(1)

    # Check if deleted points were visible during search
    if deleted_visibility:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — {len(deleted_visibility)} deleted points were visible during search")
        try:
            safe_request("DELETE", f"/collections/{COLL}")
        except:
            pass
        sys.exit(1)

    # Final verification: deleted points should not be in search results
    query_vector = [0.1] * VECTOR_DIM
    search_body = {
        "vector": query_vector,
        "limit": 10000,
        "with_payload": True
    }

    status, body, raw = safe_request("POST", f"/collections/{COLL}/points/search", json=search_body)

    if status != 200:
        print(f"VERDICT: SCRIPT_ERROR — Final search failed with status {status}")
        try:
            safe_request("DELETE", f"/collections/{COLL}")
        except:
            pass
        sys.exit(2)

    try:
        results = body.get("result", [])
        found_ids = [r.get("id") for r in results]

        # Check if any deleted IDs are still present
        still_visible = [pid for pid in points_to_delete if pid in found_ids]
        if still_visible:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Deleted points still visible after delete: {still_visible[:5]}")
            try:
                safe_request("DELETE", f"/collections/{COLL}")
            except:
                pass
            sys.exit(1)

        # Verify non-deleted points are still visible
        expected_kept = list(range(NUM_POINTS // 2, NUM_POINTS))
        missing_kept = [pid for pid in expected_kept if pid not in found_ids]
        if len(missing_kept) > 5:  # Allow small tolerance
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Too many non-deleted points missing: {len(missing_kept)}")
            try:
                safe_request("DELETE", f"/collections/{COLL}")
            except:
                pass
            sys.exit(1)

    except Exception as e:
        print(f"VERDICT: SCRIPT_ERROR — Failed to parse final results: {e}")
        try:
            safe_request("DELETE", f"/collections/{COLL}")
        except:
            pass
        sys.exit(2)

    print("VERDICT: NO_DEFECT")

    # Cleanup
    try:
        safe_request("DELETE", f"/collections/{COLL}")
    except Exception:
        pass

if __name__ == "__main__":
    main()
