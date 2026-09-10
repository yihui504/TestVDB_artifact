#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: chroma v1.5.9
Attack: type_confusion
Constraint: IDs must be non-empty strings or integers
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
    """Test: None/integer as ID should be handled correctly"""
    import chromadb

    try:
        client = chromadb.HttpClient(host=BASE_URL.split("://")[1].split(":")[0],
                                     port=int(BASE_URL.split(":")[-1]) if ":" in BASE_URL else 8000)

        # Setup
        collection_name = "test_id_type_confusion"
        try:
            client.delete_collection(collection_name)
        except:
            pass

        collection = client.create_collection(name=collection_name)
        print(f"Status: Setup complete")

        # Act: attempt to add with None as ID
        try:
            collection.add(
                ids=[None],  # Violation: None is not valid ID
                embeddings=[[0.1] * 128],
                metadatas=[{"category": "test"}]
            )
            print(f"Status: Document with None ID added successfully")
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — None ID should be rejected")
            return

        except (ValueError, TypeError) as e:
            print(f"Status: Rejected with {type(e).__name__}")
            print(f"Body: {str(e)}")

            error_msg = str(e).lower()
            if "id" not in error_msg:
                print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — Error should mention 'id'")
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
