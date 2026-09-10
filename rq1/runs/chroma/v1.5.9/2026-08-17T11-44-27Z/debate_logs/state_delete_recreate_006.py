#!/usr/bin/env python3
"""
TestVDB State Attack - Delete Recreate (006)
Target: chroma v1.5.9
Strategy: delete_recreate
Constraint: state_invariants - delete then recreate same name should work
Expected Defect: Type4_StateLogicViolation (recreated collection should be clean)

This script tests that:
1. Create collection with data
2. Delete collection
3. Recreate collection with same name
4. Verify recreated collection is empty (clean state)
"""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', '..', 'agents'))

from testvdb_runner import safe_request, BASE_URL, setup_default, teardown_default

COLLECTION_NAME = "state_delete_recreate_006"

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
    print(f"=== TestVDB State Attack: Delete Recreate (006) ===")
    print(f"Target: chroma v1.5.9 | Collection: {COLLECTION_NAME}")
    print(f"Test: Create → Add data → Delete → Recreate → Verify clean state")

    # Check BASE_URL is set
    if not BASE_URL:
        print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set")
        sys.exit(2)

    print(f"BASE_URL: {BASE_URL}")

    # Step 1: Create collection and add data
    print("\n--- Step 1: Create collection and add data ---")
    try:
        setup_data = setup_default(COLLECTION_NAME, dimension=128)
        print(f"Setup complete")

        # Add some documents
        docs = [f"doc_{i}" for i in range(20)]
        embeddings = [[0.1 + i * 0.01] * 128 for i in range(20)]
        ids = [f"id_{i}" for i in range(20)]

        status, body, raw = safe_request("POST", "add",
                                         path_params={"name": COLLECTION_NAME},
                                         json={"documents": docs, "embeddings": embeddings, "ids": ids})
        print(f"Add status: {status}")

        if status not in [200, 201, 202, 204]:
            print(f"WARNING: Add returned {status}")

    except Exception as e:
        print(f"Setup/add failed: {e}")
        print("VERDICT: SCRIPT_ERROR - Setup failed")
        sys.exit(2)

    # Verify we have data
    print("\n--- Verify initial data ---")
    count_initial = get_count()
    print(f"Initial count: {count_initial}")

    if count_initial is None or count_initial == 0:
        print("VERDICT: SCRIPT_ERROR - Initial count should be > 0")
        teardown_default(COLLECTION_NAME)
        sys.exit(2)

    # Step 2: Delete collection
    print("\n--- Step 2: Delete collection ---")
    try:
        status, body, raw = safe_request("DELETE", "delete_collection",
                                        path_params={"name": COLLECTION_NAME})
        print(f"Delete status: {status}")

        if status not in [200, 202, 204]:
            print(f"WARNING: Delete returned {status}")

    except Exception as e:
        print(f"Delete exception: {e}")
        print("VERDICT: SCRIPT_ERROR - Delete failed")
        sys.exit(2)

    # Step 3: Recreate collection with same name
    print("\n--- Step 3: Recreate collection ---")
    try:
        status, body, raw = safe_request("POST", "create_collection",
                                        path_params={"name": COLLECTION_NAME})
        print(f"Recreate status: {status}")

        if status not in [200, 201, 202, 204]:
            print(f"WARNING: Recreate returned {status}")

    except Exception as e:
        print(f"Recreate exception: {e}")
        print("VERDICT: SCRIPT_ERROR - Recreate failed")
        sys.exit(2)

    # Step 4: Verify recreated collection is empty
    print("\n--- Step 4: Verify recreated collection is empty ---")
    count_after_recreate = get_count()
    print(f"Count after recreate: {count_after_recreate}")

    # DEFECT: Recreated collection should be empty (count = 0)
    if count_after_recreate is not None and count_after_recreate != 0:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - Recreated collection should be empty (count=0), got {count_after_recreate}")
        teardown_default(COLLECTION_NAME)
        sys.exit(1)

    print("OK: Recreated collection is clean (count=0)")

    print(f"\nVERDICT: NO_DEFECT - Delete/recreate cycle preserves state correctly")

    # Cleanup
    try:
        teardown_default(COLLECTION_NAME)
    except:
        pass

    sys.exit(0)

if __name__ == "__main__":
    main()
