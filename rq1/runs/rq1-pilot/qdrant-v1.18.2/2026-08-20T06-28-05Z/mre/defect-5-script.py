#!/usr/bin/env python3
"""MRE for TESTVDB-QDRANT-005: Query Filter - Type Mismatch in filter.match.value Handling"""
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
    # Step 1: Setup - create a test collection with payload
    collection_name = "mre_test_filter_mismatch"
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

    # Insert a point with a keyword payload
    status, body = safe_request("PUT", f"/collections/{collection_name}/points", json={
        "points": [{
            "id": 1,
            "vector": [0.1] * 128,
            "payload": {
                "category": "electronics"
            }
        }]
    })

    if status not in (200, 201):
        print(f"Setup failed: could not insert point (status {status})")
        cleanup_collection(collection_name)
        return False

    # Step 2: Trigger the defect - query with type mismatch in filter.match.value
    # Use integer when keyword is expected
    status, body = safe_request("POST", f"/collections/{collection_name}/points/query", json={
        "filter": {
            "must": [
                {
                    "key": "category",
                    "match": {
                        "value": 123  # Type mismatch: number vs keyword
                    }
                }
            ]
        }
    })

    print(f"Status: {status}")
    print(f"Body: {json.dumps(body, indent=2, ensure_ascii=False) if isinstance(body, dict) else body}")

    # Step 3: Verify - should handle type mismatch with clear error
    if status == 200:
        print("\nVERDICT: DEFECT_REPRODUCED (Type2_PoorDiagnostics)")
        print("Expected: Clear error for type mismatch in filter.match.value")
        print(f"Actual: {status} - API accepted or silently failed")
        cleanup_collection(collection_name)
        return True
    elif status in (400, 422):
        # Check if error message mentions the type issue
        body_str = json.dumps(body) if isinstance(body, dict) else str(body)
        if "type" in body_str.lower() or "match" in body_str.lower():
            print("\nVERDICT: NOT_REPRODUCED")
            print("API correctly rejected with clear error message")
            cleanup_collection(collection_name)
            return False
        else:
            print("\nVERDICT: DEFECT_REPRODUCED (Type2_PoorDiagnostics)")
            print("Expected: Error message should mention type/match issue")
            print(f"Actual: {status} - Error message unclear")
            cleanup_collection(collection_name)
            return True
    else:
        print(f"\nVERDICT: INCONCLUSIVE (unexpected status {status})")
        cleanup_collection(collection_name)
        return False

if __name__ == "__main__":
    sys.exit(1 if reproduce() else 0)
