#!/usr/bin/env python3
"""MRE for TESTVDB-QDRANT-001: Collections Create - hnsw_config.m Parameter Validation Missing"""
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
    # Step 1: Cleanup
    collection_name = "mre_test_m_1"
    cleanup_collection(collection_name)

    # Step 2: Trigger the defect - create collection with m=1 (below minimum 2)
    status, body = safe_request("PUT", f"/collections/{collection_name}", json={
        "vectors": {
            "size": 128,
            "distance": "Cosine"
        },
        "hnsw_config": {
            "m": 1
        }
    })

    print(f"Status: {status}")
    print(f"Body: {json.dumps(body, indent=2, ensure_ascii=False) if isinstance(body, dict) else body}")

    # Step 3: Verify - should return 4xx, not 200
    if status == 200:
        print("\nVERDICT: DEFECT_REPRODUCED")
        print("Expected: 4xx (m=1 violates constraint m >= 2)")
        print(f"Actual: {status} - API accepted invalid parameter")
        cleanup_collection(collection_name)
        return True
    elif status in (400, 422):
        print("\nVERDICT: NOT_REPRODUCED")
        print("API correctly rejected invalid parameter")
        cleanup_collection(collection_name)
        return False
    else:
        print(f"\nVERDICT: INCONCLUSIVE (unexpected status {status})")
        cleanup_collection(collection_name)
        return False

if __name__ == "__main__":
    sys.exit(1 if reproduce() else 0)
