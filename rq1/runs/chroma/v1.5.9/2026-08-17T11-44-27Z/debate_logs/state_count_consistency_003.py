#!/usr/bin/env python3
"""
TestVDB State Attack - Count Consistency (003)
Target: chroma v1.5.9
Strategy: count_consistency
Constraint: state_invariants - insert_count_consistency
Expected Defect: Type4_StateLogicViolation (count should equal number of inserted documents)

This script tests that:
1. Create collection
2. Get initial count (should be 0)
3. Add N documents
4. Get count again (should be N)
5. Delete M documents
6. Get count again (should be N-M)
"""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', '..', 'agents'))

from testvdb_runner import safe_request, BASE_URL, setup_default, teardown_default

COLLECTION_NAME = "state_count_consistency_003"
NUM_DOCS = 50
DELETE_DOCS = 15

def get_count():
    """Get current document count from collection"""
    try:
        status, body, raw = safe_request("GET", "get_collection",
                                        path_params={"name": COLLECTION_NAME})
        print(f"Get count status: {status}")
        print(f"Get count raw: {raw[:300]}")

        if status == 200:
            # Try to extract count from response
            # Chroma's response structure may vary, so we check multiple possible keys
            if isinstance(body, dict):
                if "count" in body:
                    return body["count"]
                if "metadata" in body and isinstance(body["metadata"], dict):
                    if "count" in body["metadata"]:
                        return body["metadata"]["count"]
                if "result" in body and isinstance(body["result"], dict):
                    if "count" in body["result"]:
                        return body["result"]["count"]

            # If we can't find count, return None
            print(f"WARNING: Could not extract count from response")
            return None

        return None

    except Exception as e:
        print(f"Get count exception: {e}")
        return None

def main():
    print(f"=== TestVDB State Attack: Count Consistency (003) ===")
    print(f"Target: chroma v1.5.9 | Collection: {COLLECTION_NAME}")
    print(f"Test: Add {NUM_DOCS} docs, delete {DELETE_DOCS}, verify counts")

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

    # Step 1: Get initial count (should be 0)
    print("\n--- Step 1: Get initial count ---")
    count_before = get_count()
    print(f"Initial count: {count_before}")

    if count_before is not None and count_before != 0:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - Initial count should be 0, got {count_before}")
        teardown_default(COLLECTION_NAME)
        sys.exit(1)

    # Step 2: Add documents
    print(f"\n--- Step 2: Add {NUM_DOCS} documents ---")
    try:
        docs = [f"doc_{i}" for i in range(NUM_DOCS)]
        embeddings = [[0.1 + i * 0.01] * 128 for i in range(NUM_DOCS)]
        ids = [f"id_{i}" for i in range(NUM_DOCS)]

        status, body, raw = safe_request("POST", "add",
                                         path_params={"name": COLLECTION_NAME},
                                         json={"documents": docs, "embeddings": embeddings, "ids": ids})
        print(f"Add status: {status}")
        print(f"Add raw: {raw[:300]}")

        if status not in [200, 201, 202, 204]:
            print(f"WARNING: Add returned {status}, expected 2xx")

    except Exception as e:
        print(f"Add exception: {e}")
        print("VERDICT: SCRIPT_ERROR - Add failed")
        teardown_default(COLLECTION_NAME)
        sys.exit(2)

    # Step 3: Get count after adding (should be NUM_DOCS)
    print(f"\n--- Step 3: Get count after adding ---")
    count_after_add = get_count()
    print(f"Count after add: {count_after_add}")

    if count_after_add is not None and count_after_add != NUM_DOCS:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - Expected count {NUM_DOCS}, got {count_after_add}")
        teardown_default(COLLECTION_NAME)
        sys.exit(1)

    # Step 4: Delete some documents
    print(f"\n--- Step 4: Delete {DELETE_DOCS} documents ---")
    try:
        ids_to_delete = [f"id_{i}" for i in range(DELETE_DOCS)]

        status, body, raw = safe_request("POST", "delete",
                                         path_params={"name": COLLECTION_NAME},
                                         json={"ids": ids_to_delete})
        print(f"Delete status: {status}")
        print(f"Delete raw: {raw[:300]}")

        if status not in [200, 202, 204]:
            print(f"WARNING: Delete returned {status}, expected 2xx")

    except Exception as e:
        print(f"Delete exception: {e}")
        print("VERDICT: SCRIPT_ERROR - Delete failed")
        teardown_default(COLLECTION_NAME)
        sys.exit(2)

    # Step 5: Get count after deleting (should be NUM_DOCS - DELETE_DOCS)
    print(f"\n--- Step 5: Get count after deleting ---")
    expected_final = NUM_DOCS - DELETE_DOCS
    count_final = get_count()
    print(f"Count after delete: {count_final}")
    print(f"Expected: {expected_final}")

    if count_final is not None and count_final != expected_final:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - Expected count {expected_final}, got {count_final}")
        teardown_default(COLLECTION_NAME)
        sys.exit(1)

    print(f"\nVERDICT: NO_DEFECT - All count operations consistent")

    # Cleanup
    try:
        teardown_default(COLLECTION_NAME)
    except:
        pass

    sys.exit(0)

if __name__ == "__main__":
    main()
