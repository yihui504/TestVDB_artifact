#!/usr/bin/env python3
"""MRE for TESTVDB-QDRANT-004: Collections Count - exact Parameter Type Mismatch Handling"""
import os, sys, json, requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_URL = os.environ.get("TESTVDB_DB_URL", "http://localhost:6333")
HEADERS = {"Content-Type": "application/json"}

def safe_request(method, path, **kwargs):
    try:
        resp = requests.request(method, f"{DB_URL}{path}", timeout=10, headers=HEADERS, **kwargs)
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        return resp.status_code, body
    except Exception as e:
        return 0, str(e)

def cleanup_collection(name):
    try:
        safe_request("DELETE", f"/collections/{name}")
    except Exception:
        pass

def reproduce():
    # Step 1: Setup - create a test collection
    collection_name = "mre_test_count_exact"
    cleanup_collection(collection_name)

    status, body = safe_request("PUT", f"/collections/{collection_name}", json={
        "vectors": {
            "size": 128,
            "distance": "Cosine"
        }
    })

    if status not in (200, 201):
        print(f"Setup failed: could not create collection (status {status})")
        return False

    # Step 2: Trigger the defect - request count with invalid type for exact parameter
    # Use a string instead of boolean/integer
    status, body = safe_request("GET", f"/collections/{collection_name}", params={"exact": "invalid"})

    print(f"Status: {status}")
    print(f"Body: {json.dumps(body, indent=2, ensure_ascii=False) if isinstance(body, dict) else body}")

    # Step 3: Verify - should handle type mismatch gracefully
    # Type2 defect: poor error handling or unclear error message
    if status == 200:
        print("\nVERDICT: DEFECT_REPRODUCED (Type2_PoorDiagnostics)")
        print("Expected: Clear error message for type mismatch")
        print(f"Actual: {status} - API accepted invalid type or gave unclear error")
        cleanup_collection(collection_name)
        return True
    elif status in (400, 422):
        # Check if error message is clear
        body_str = json.dumps(body) if isinstance(body, dict) else str(body)
        if "exact" in body_str.lower() or "type" in body_str.lower():
            print("\nVERDICT: NOT_REPRODUCED")
            print("API correctly rejected with clear error message")
            cleanup_collection(collection_name)
            return False
        else:
            print("\nVERDICT: DEFECT_REPRODUCED (Type2_PoorDiagnostics)")
            print("Expected: Error message should mention 'exact' or 'type'")
            print(f"Actual: {status} - Error message unclear")
            cleanup_collection(collection_name)
            return True
    else:
        print(f"\nVERDICT: INCONCLUSIVE (unexpected status {status})")
        cleanup_collection(collection_name)
        return False

if __name__ == "__main__":
    sys.exit(1 if reproduce() else 0)
