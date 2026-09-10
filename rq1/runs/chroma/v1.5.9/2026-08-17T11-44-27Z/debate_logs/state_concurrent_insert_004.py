#!/usr/bin/env python3
"""
TestVDB State Attack - Concurrent Insert (004)
Target: chroma v1.5.9
Strategy: concurrent_operations
Constraint: state_invariants - concurrent inserts should not corrupt state
Expected Defect: Type3_RuntimeFailure (concurrent insert errors) or Type4_StateLogicViolation (count mismatch)

This script tests that:
1. Multiple threads concurrently insert documents
2. Verify no crashes or 500 errors
3. Verify final count matches total inserted
"""

import os
import sys
import time
import threading

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', '..', 'agents'))

from testvdb_runner import safe_request, BASE_URL, setup_default, teardown_default

COLLECTION_NAME = "state_concurrent_insert_004"
THREADS = 10
DOCS_PER_THREAD = 10

# Global for tracking successful inserts
successful_inserts = 0
insert_lock = threading.Lock()

def insert_worker(thread_id, docs_per_thread):
    """Worker thread that inserts documents"""
    global successful_inserts

    for i in range(docs_per_thread):
        try:
            doc_id = f"thread_{thread_id}_doc_{i}"
            docs = [doc_id]
            embeddings = [[0.1 + thread_id * 0.01 + i * 0.001] * 128]
            ids = [doc_id]

            status, body, raw = safe_request("POST", "add",
                                             path_params={"name": COLLECTION_NAME},
                                             json={"documents": docs, "embeddings": embeddings, "ids": ids})

            if status in [200, 201, 202, 204]:
                with insert_lock:
                    successful_inserts += 1
            elif status == 500:
                print(f"Thread {thread_id} doc {i}: 500 internal error")
                return False
            else:
                print(f"Thread {thread_id} doc {i}: unexpected status {status}")

            time.sleep(0.01)

        except Exception as e:
            print(f"Thread {thread_id} doc {i}: exception {str(e)[:60]}")
            return False

    return True

def get_count():
    """Get current document count"""
    try:
        status, body, raw = safe_request("GET", "get_collection",
                                        path_params={"name": COLLECTION_NAME})

        if status == 200 and isinstance(body, dict):
            # Try to extract count from response
            if "count" in body:
                return body["count"]
            if "metadata" in body and isinstance(body["metadata"], dict) and "count" in body["metadata"]:
                return body["metadata"]["count"]
            if "result" in body and isinstance(body["result"], dict) and "count" in body["result"]:
                return body["result"]["count"]

        return None

    except Exception as e:
        print(f"Get count exception: {e}")
        return None

def main():
    print(f"=== TestVDB State Attack: Concurrent Insert (004) ===")
    print(f"Target: chroma v1.5.9 | Collection: {COLLECTION_NAME}")
    print(f"Threads: {THREADS} | Docs per thread: {DOCS_PER_THREAD} | Total: {THREADS * DOCS_PER_THREAD}")

    # Check BASE_URL is set
    if not BASE_URL:
        print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set")
        sys.exit(2)

    print(f"BASE_URL: {BASE_URL}")

    # Setup: Create collection
    try:
        setup_data = setup_default(COLLECTION_NAME, dimension=128)
        print(f"Setup complete")
    except Exception as e:
        print(f"Setup failed: {e}")
        print("VERDICT: SCRIPT_ERROR - Setup failed")
        sys.exit(2)

    # Get initial count
    print("\n--- Initial count ---")
    count_before = get_count()
    print(f"Initial count: {count_before}")

    # Start concurrent insert threads
    print(f"\n--- Starting {THREADS} concurrent insert threads ---")
    threads = []

    for i in range(THREADS):
        thread = threading.Thread(target=insert_worker, args=(i, DOCS_PER_THREAD))
        threads.append(thread)
        thread.start()

    # Wait for all threads
    for t in threads:
        t.join()

    print(f"All threads completed")
    print(f"Successful inserts (tracked): {successful_inserts}")
    print(f"Expected inserts: {THREADS * DOCS_PER_THREAD}")

    # Give time for operations to settle
    time.sleep(2)

    # Get final count
    print("\n--- Final count ---")
    count_after = get_count()
    print(f"Final count: {count_after}")

    expected_total = THREADS * DOCS_PER_THREAD

    # DEFECT CHECK 1: Count mismatch
    if count_after is not None and count_after != expected_total:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - Expected count {expected_total}, got {count_after}")
        teardown_default(COLLECTION_NAME)
        sys.exit(1)

    # DEFECT CHECK 2: Successful inserts < expected (due to errors)
    if successful_inserts < expected_total:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - Only {successful_inserts}/{expected_total} inserts succeeded")
        teardown_default(COLLECTION_NAME)
        sys.exit(1)

    print(f"\nVERDICT: NO_DEFECT - All concurrent inserts succeeded, count matches")

    # Cleanup
    try:
        teardown_default(COLLECTION_NAME)
    except:
        pass

    sys.exit(0)

if __name__ == "__main__":
    main()
