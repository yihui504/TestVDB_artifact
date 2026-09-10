#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: chroma v1.5.9
Attack: type_confusion
Constraint: IDs and embeddings arrays must be non-empty
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
    """Test: empty arrays for IDs/embeddings should be rejected"""
    import chromadb

    try:
        client = chromadb.HttpClient(host=BASE_URL.split("://")[1].split(":")[0],
                                     port=int(BASE_URL.split(":")[-1]) if ":" in BASE_URL else 8000)

        # Setup
        collection_name = "test_empty_arrays"
        try:
            client.delete_collection(collection_name)
        except:
            pass

        collection = client.create_collection(name=collection_name)
        print(f"Status: Setup complete")

        # Act: attempt to add with empty arrays
        try:
            collection.add(
                ids=[],  # Violation: empty array
                embeddings=[],
                metadatas=[]
            )
            print(f"Status: Empty arrays accepted successfully")
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — Empty arrays should be rejected")
            return

        except ValueError as e:
            print(f"Status: Rejected with ValueError")
            print(f"Body: {str(e)}")

            error_msg = str(e).lower()
            if "empty" not in error_msg and "ids" not in error_msg:
                print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — Error should mention 'empty' or 'ids'")
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
