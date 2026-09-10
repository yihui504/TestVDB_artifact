#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: chroma v1.5.9
Attack: boundary_value_violation
Constraint: deleting nonexistent collection should fail gracefully
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
    """Test: deleting nonexistent collection should be handled correctly"""
    import chromadb

    try:
        client = chromadb.HttpClient(host=BASE_URL.split("://")[1].split(":")[0],
                                     port=int(BASE_URL.split(":")[-1]) if ":" in BASE_URL else 8000)

        print(f"Status: Setup complete")

        # Act: attempt to delete nonexistent collection
        try:
            client.delete_collection("nonexistent_collection_xyz123")
            print(f"Status: Delete succeeded for nonexistent collection")
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — Deleting nonexistent collection should fail")
            return

        except ValueError as e:
            print(f"Status: Rejected with ValueError")
            print(f"Body: {str(e)}")

            error_msg = str(e).lower()
            if "collection" not in error_msg and "not" not in error_msg and "exist" not in error_msg:
                print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — Error should mention 'collection' or 'not found'")
                return

            print("VERDICT: NO_DEFECT")
            return

        except Exception as e:
            print(f"Status: Unexpected error - {type(e).__name__}")
            print(f"Body: {str(e)}")

            # Chroma may ignore deletion of nonexistent collections
            # This could be considered a defect (silent failure)
            if "not" in str(e).lower() or "exist" in str(e).lower():
                print(f"VERDICT: NO_DEFECT — Correctly raises error for nonexistent collection")
            else:
                print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — Silent deletion of nonexistent collection")
            return

    except Exception as e:
        print(f"Status: 0")
        print(f"Body: Connection error - {str(e)}")
        print("VERDICT: SCRIPT_ERROR — Chroma client initialization failed")
        return

if __name__ == "__main__":
    test_boundary()
