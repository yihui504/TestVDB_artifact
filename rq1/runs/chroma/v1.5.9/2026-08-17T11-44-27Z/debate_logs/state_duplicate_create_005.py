#!/usr/bin/env python3
"""
TestVDB State Attack - Duplicate Create (005)
Target: chroma v1.5.9
Strategy: duplicate_create
Constraint: state_invariants - duplicate collection name handling
Expected Defect: Type1_IllegalSuccess (duplicate create should fail) or Type4_StateLogicViolation (duplicate creates corrupt state)

This script tests that:
1. Create collection with name X
2. Try to create collection with same name X again
3. Verify behavior: should return 409 Conflict or 400, not 200 success
4. Verify state is not corrupted after duplicate attempt
"""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', '..', 'agents'))

from testvdb_runner import safe_request, BASE_URL, setup_default, teardown_default

COLLECTION_NAME = "state_duplicate_create_005"

def main():
    print(f"=== TestVDB State Attack: Duplicate Create (005) ===")
    print(f"Target: chroma v1.5.9 | Collection: {COLLECTION_NAME}")
    print(f"Test: Create collection, then try to create again with same name")

    # Check BASE_URL is set
    if not BASE_URL:
        print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set")
        sys.exit(2)

    print(f"BASE_URL: {BASE_URL}")

    # Step 1: Create collection (first time - should succeed)
    print("\n--- Step 1: Create collection (first time) ---")
    try:
        status, body, raw = safe_request("POST", "create_collection",
                                        path_params={"name": COLLECTION_NAME})
        print(f"First create status: {status}")
        print(f"First create raw: {raw[:300]}")

        if status not in [200, 201, 202, 204]:
            print(f"WARNING: First create returned {status}, expected 2xx")

    except Exception as e:
        print(f"First create exception: {e}")
        print("VERDICT: SCRIPT_ERROR - First create failed")
        sys.exit(2)

    # Step 2: Try to create same collection again (should fail or return error)
    print("\n--- Step 2: Create collection with same name (duplicate) ---")
    try:
        status, body, raw = safe_request("POST", "create_collection",
                                        path_params={"name": COLLECTION_NAME})
        print(f"Duplicate create status: {status}")
        print(f"Duplicate create raw: {raw[:300]}")

        # DEFECT: If duplicate create returns 200/201 (success)
        if status in [200, 201, 204]:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - Duplicate create returned {status} (should be 409/400)")
            teardown_default(COLLECTION_NAME)
            sys.exit(1)

        # 409 Conflict or 400 Bad Request is correct behavior
        if status in [409, 400, 422]:
            print(f"OK: Duplicate create returned {status} (expected)")

    except Exception as e:
        print(f"Duplicate create exception (may be expected): {e}")

    # Step 3: Verify the first collection still exists and is usable
    print("\n--- Step 3: Verify collection still works ---")
    try:
        # Try to add a document
        docs = ["test_doc"]
        embeddings = [[0.1] * 128]
        ids = ["test_id"]

        status, body, raw = safe_request("POST", "add",
                                        path_params={"name": COLLECTION_NAME},
                                        json={"documents": docs, "embeddings": embeddings, "ids": ids})
        print(f"Add after duplicate create status: {status}")

        if status not in [200, 201, 202, 204]:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - Collection corrupted after duplicate create (add returned {status})")
            teardown_default(COLLECTION_NAME)
            sys.exit(1)

        print("OK: Collection still usable after duplicate create")

    except Exception as e:
        print(f"Add after duplicate create exception: {e}")
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) - Collection may be corrupted")
        teardown_default(COLLECTION_NAME)
        sys.exit(1)

    print(f"\nVERDICT: NO_DEFECT - Duplicate create handled correctly, collection not corrupted")

    # Cleanup
    try:
        teardown_default(COLLECTION_NAME)
    except:
        pass

    sys.exit(0)

if __name__ == "__main__":
    main()
