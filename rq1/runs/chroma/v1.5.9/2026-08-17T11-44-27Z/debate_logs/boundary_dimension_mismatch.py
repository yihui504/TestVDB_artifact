#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: chroma v1.5.9
Attack: dimension_mismatch
Constraint: vector dimensions must match during add/query
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
    """Test: vector dimension mismatch should be rejected"""
    import chromadb

    try:
        client = chromadb.HttpClient(host=BASE_URL.split("://")[1].split(":")[0],
                                     port=int(BASE_URL.split(":")[-1]) if ":" in BASE_URL else 8000)

        # Setup: create collection with 128-dimensional vectors
        try:
            collection = client.create_collection(
                name="test_dim_mismatch",
                metadata={"dimension": "128"}
            )
            print(f"Status: Collection created")
        except Exception as e:
            print(f"Status: Collection creation failed - {str(e)}")
            print("VERDICT: SCRIPT_ERROR — Setup failed")
            return

        # Act: add vectors with wrong dimension (64 != 128)
        try:
            collection.add(
                ids=["test1"],
                embeddings=[[0.1] * 64],  # Wrong: 64 dimensions
                metadatas=[{"category": "test"}]
            )
            print(f"Status: Vectors added successfully")
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — Wrong dimension vectors should be rejected")
            return

        except ValueError as e:
            print(f"Status: Rejected with ValueError")
            print(f"Body: {str(e)}")

            error_msg = str(e).lower()
            if "dimension" not in error_msg and "embedding" not in error_msg:
                print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — Error should mention 'dimension' or 'embedding'")
                return

            print("VERDICT: NO_DEFECT")
            return

        except Exception as e:
            print(f"Status: Unexpected error - {type(e).__name__}")
            print(f"Body: {str(e)}")

            # Chroma may accept any dimension silently - this is still a defect
            if "dimension" not in str(e).lower():
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — Dimension mismatch silently accepted")
                return

            print(f"VERDICT: NO_DEFECT")
            return

    except Exception as e:
        print(f"Status: 0")
        print(f"Body: Connection error - {str(e)}")
        print("VERDICT: SCRIPT_ERROR — Chroma client initialization failed")
        return

if __name__ == "__main__":
    test_boundary()
