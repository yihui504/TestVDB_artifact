#!/usr/bin/env python3
"""MRE for TESTVDB-QDRANT-006: Points Search - score_threshold Parameter Validation Missing"""
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
    # Step 1: Setup - create a test collection with data
    collection_name = "mre_test_score_threshold"
    vector_dim = 128
    cleanup_collection(collection_name)

    status, body = safe_request("PUT", f"/collections/{collection_name}", json={
        "vectors": {
            "size": vector_dim,
            "distance": "Cosine"
        }
    })

    if status not in (200, 201):
        print(f"Setup failed: could not create collection (status {status})")
        return False

    # Insert test point
    status, body = safe_request("PUT", f"/collections/{collection_name}/points", json={
        "points": [{
            "id": 1,
            "vector": [0.1] * vector_dim
        }]
    })

    if status not in (200, 201):
        print(f"Setup failed: could not insert point (status {status})")
        cleanup_collection(collection_name)
        return False

    # Step 2: Trigger the defect - search with score_threshold=-0.1 (below minimum 0)
    status, body = safe_request("POST", f"/collections/{collection_name}/points/search", json={
        "vector": [0.2] * vector_dim,
        "limit": 10,
        "score_threshold": -0.1
    })

    print(f"Status: {status}")
    print(f"Body: {json.dumps(body, indent=2, ensure_ascii=False) if isinstance(body, dict) else body}")

    # Step 3: Verify - should return 4xx, not 200
    if status == 200:
        print("\nVERDICT: DEFECT_REPRODUCED")
        print("Expected: 4xx (score_threshold=-0.1 violates constraint score_threshold >= 0)")
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
