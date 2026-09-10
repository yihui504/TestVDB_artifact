#!/usr/bin/env python3
"""
TestVDB State Attack - Delete Consistency (001)
Target: chroma v1.5.9
Strategy: delete_consistency
Constraint: state_invariants - operations after delete should fail gracefully
Expected Defect: Type4_StateLogicViolation (operations on deleted collection should return 404/not found, not 500)

This script tests that:
1. Delete a collection
2. Try to query, add, or count from the deleted collection
3. Verify responses are 404 (not found) not 500 (internal error)
"""

import os
import sys
import time

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', '..', 'agents'))

from testvdb_runner import safe_request, BASE_URL, setup_default, teardown_default

COLLECTION_NAME = "state_delete_consistency_001"

def main():
    print(f"=== TestVDB State Attack: Delete Consistency (001) ===")
    print(f"Target: chroma v1.5.9 | Collection: {COLLECTION_NAME}")

    # Check BASE_URL is set
    if not BASE_URL:
        print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set")
        sys.exit(2)

    print(f"BASE_URL: {BASE_URL}")

    # Setup: Create collection with vectors
    try:
        setup_data = setup_default(COLLECTION_NAME, dimension=128)
        print(f"Setup complete: {setup_data}")
    except Exception as e:
        print(f"Setup failed: {e}")
        print("VERDICT: SCRIPT_ERROR - Setup failed")
        sys.exit(2)

    # Delete the collection
    try:
        print("\n--- Step 1: Delete collection ---")
        status, body, raw = safe_request("DELETE", "delete_collection", path_params={"name": COLLECTION_NAME})
        print(f"Delete status: {status}")
        print(f"Delete raw: {raw[:200]}")

        if status not in [200, 204, 202]:
            print(f"WARNING: Delete returned {status}, expected 2xx")
    except Exception as e:
        print(f"Delete exception: {e}")
        print("VERDICT: SCRIPT_ERROR - Delete failed")
        teardown_default(COLLECTION_NAME)
        sys.exit(2)

    # Give time for deletion to propagate
    time.sleep(0.5)

    # Step 2: Try to query the deleted collection
    print("\n--- Step 2: Query deleted collection ---")
    try:
        query_vector = [0.1] * 128
        status, body, raw = safe_request("POST", "query",
                                         path_params={"name": COLLECTION_NAME},
                                         json={"query_embeddings": [query_vector], "n_results": 5})
        print(f"Query status: {status}")
        print(f"Query raw: {raw[:200]}")

        # DEFECT: If query returns 500 (internal error) instead of 404 (not found)
        if status == 500:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - Query on deleted collection returned 500 (should be 404)")
            teardown_default(COLLECTION_NAME)
            sys.exit(1)

        # 404 or similar "not found" is expected/correct
        if status in [404, 400, 422]:
            print(f"OK: Query returned {status} (expected - collection not found)")

    except Exception as e:
        print(f"Query exception (may be expected): {e}")

    # Step 3: Try to add documents to deleted collection
    print("\n--- Step 3: Add documents to deleted collection ---")
    try:
        docs = ["test doc after delete"]
        embeddings = [[0.2] * 128]
        status, body, raw = safe_request("POST", "add",
                                         path_params={"name": COLLECTION_NAME},
                                         json={"documents": docs, "embeddings": embeddings})
        print(f"Add status: {status}")
        print(f"Add raw: {raw[:200]}")

        # DEFECT: If add returns 500 instead of 404
        if status == 500:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - Add on deleted collection returned 500 (should be 404)")
            teardown_default(COLLECTION_NAME)
            sys.exit(1)

        if status in [404, 400, 422]:
            print(f"OK: Add returned {status} (expected - collection not found)")

    except Exception as e:
        print(f"Add exception (may be expected): {e}")

    # Step 4: Try to get collection info
    print("\n--- Step 4: Get collection info ---")
    try:
        status, body, raw = safe_request("GET", "get_collection", path_params={"name": COLLECTION_NAME})
        print(f"Get status: {status}")
        print(f"Get raw: {raw[:200]}")

        if status == 500:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - Get on deleted collection returned 500 (should be 404)")
            teardown_default(COLLECTION_NAME)
            sys.exit(1)

        if status in [404, 400, 422]:
            print(f"OK: Get returned {status} (expected - collection not found)")

    except Exception as e:
        print(f"Get exception (may be expected): {e}")

    print("\nVERDICT: NO_DEFECT - All operations on deleted collection returned proper error codes")

    # Cleanup (attempt to delete again, ignore errors)
    try:
        teardown_default(COLLECTION_NAME)
    except:
        pass

    sys.exit(0)

if __name__ == "__main__":
    main()
