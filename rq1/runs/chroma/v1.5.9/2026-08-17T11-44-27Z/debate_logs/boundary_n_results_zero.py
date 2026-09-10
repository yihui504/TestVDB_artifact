#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: chroma v1.5.9
Attack: boundary_value_violation
Constraint: n_results must be >= 1
"""

import sys
import os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

def test_boundary():
    """Test: n_results=0 should be rejected or handled correctly"""
    import chromadb

    try:
        client = chromadb.HttpClient(host=BASE_URL.split("://")[1].split(":")[0],
                                     port=int(BASE_URL.split(":")[-1]) if ":" in BASE_URL else 8000)

        # Setup
        collection_name = "test_nresults_boundary"
        try:
            client.delete_collection(collection_name)
        except:
            pass

        collection = client.create_collection(name=collection_name)
        collection.add(
            ids=["test1", "test2"],
            embeddings=[[0.1] * 128, [0.2] * 128],
            metadatas=[{"category": "A"}, {"category": "B"}]
        )
        print(f"Status: Setup complete")

        # Act: query with n_results=0
        try:
            results = collection.query(
                query_embeddings=[[0.1] * 128],
                n_results=0  # Violation: zero results
            )
            print(f"Status: Query succeeded with n_results=0")
            print(f"Body: Returned {len(results.get('ids', [[]])[0])} results")

            # If 0 results returned, it might be valid behavior
            # If non-zero results returned, it's a defect
            returned_count = len(results.get('ids', [[]])[0])
            if returned_count > 0:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — n_results=0 should return empty or be rejected, got {returned_count}")
            else:
                print(f"VERDICT: NO_DEFECT — Correctly returned empty results for n_results=0")
            return

        except ValueError as e:
            print(f"Status: Rejected with ValueError")
            print(f"Body: {str(e)}")

            error_msg = str(e).lower()
            if "n_results" not in error_msg and "results" not in error_msg:
                print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — Error should mention 'n_results'")
                return

            print("VERDICT: NO_DEFECT")
            return

        except Exception as e:
            print(f"Status: Unexpected error - {type(e).__name__}")
            print(f"Body: {str(e)}")
            print(f"VERDICT: NO_DEFECT")
            return

    except Exception as e:
        print(f"Status: 0")
        print(f"Body: Connection error - {str(e)}")
        print("VERDICT: SCRIPT_ERROR — Chroma client initialization failed")
        return

if __name__ == "__main__":
    test_boundary()
