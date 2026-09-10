#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: chroma v1.5.9
Attack: boundary_value_violation
Constraint: collection name must be non-empty string
"""

import sys
import os

# Windows encoding compatibility
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

def test_boundary():
    """Test: collection name empty string should be rejected"""
    import chromadb

    # Arrange: Chroma SDK-first approach
    try:
        client = chromadb.HttpClient(host=BASE_URL.split("://")[1].split(":")[0],
                                     port=int(BASE_URL.split(":")[-1]) if ":" in BASE_URL else 8000)

        # Act: attempt to create collection with empty name
        try:
            collection = client.create_collection(
                name="",  # Violation: empty string
                metadata={"description": "test"}
            )
            print(f"Status: Collection created successfully")
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — Empty collection name should be rejected")
            return

        except ValueError as e:
            print(f"Status: Rejected with ValueError")
            print(f"Body: {str(e)}")

            # Type-2 check: error message quality
            error_msg = str(e).lower()
            if "name" not in error_msg and "empty" not in error_msg:
                print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — Error message should mention 'name' or 'empty'")
                return

            print("VERDICT: NO_DEFECT")
            return

        except Exception as e:
            print(f"Status: Unexpected error - {type(e).__name__}")
            print(f"Body: {str(e)}")
            print(f"VERDICT: NO_DEFECT — Rejected with different exception type")
            return

    except Exception as e:
        print(f"Status: 0")
        print(f"Body: Connection error - {str(e)}")
        print("VERDICT: SCRIPT_ERROR — Chroma client initialization failed")
        return

if __name__ == "__main__":
    test_boundary()
