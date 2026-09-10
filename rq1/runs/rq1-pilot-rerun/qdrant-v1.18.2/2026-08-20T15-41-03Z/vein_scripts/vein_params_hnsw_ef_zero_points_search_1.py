"""
TestVDB Attack Script - Vein Mining (params nested object condition)
Target: qdrant v1.18.2
Strategy: vein_params_boundary
Condition: params.hnsw_ef boundary value validation in POST /points/search
Defect Type: Type1_IllegalSuccess
"""

import requests
import os

def safe_request(method, url, **kwargs):
    """Wrapper for safe HTTP requests with timeout"""
    try:
        resp = requests.request(method, url, timeout=10, **kwargs)
        return resp.status_code, resp.headers.get('content-type', ''), resp.text
    except Exception as e:
        return 0, '', str(e)

def main():
    db_url = os.environ.get("TESTVDB_DB_URL", "http://localhost:6333")
    collection = "vein_test_params_hnsw_ef"

    # Setup: Create collection
    safe_request("DELETE", f"{db_url}/collections/{collection}")
    create_resp = safe_request("PUT", f"{db_url}/collections/{collection}",
        json={"vectors": {"size": 4, "distance": "Cosine"}})

    if create_resp[0] != 200:
        print(f"SETUP_FAILED: Could not create collection")
        return

    # Insert test points
    upsert_resp = safe_request("PUT", f"{db_url}/collections/{collection}/points",
        json={"points": [
            {"id": 1, "vector": [1.0, 0.0, 0.0, 0.0]},
            {"id": 2, "vector": [0.0, 1.0, 0.0, 0.0]}
        ]})

    # Test: Search with params.hnsw_ef=0 (boundary violation - min is 1)
    search_resp = safe_request("POST", f"{db_url}/collections/{collection}/points/search",
        json={"vector": [1.0, 0.0, 0.0, 0.0], "limit": 10, "params": {"hnsw_ef": 0}})

    # Control group: Verify hnsw_ef=-1 is correctly rejected
    control_resp = safe_request("POST", f"{db_url}/collections/{collection}/points/search",
        json={"vector": [1.0, 0.0, 0.0, 0.0], "limit": 10, "params": {"hnsw_ef": -1}})

    # Cleanup
    safe_request("DELETE", f"{db_url}/collections/{collection}")

    # Analysis
    if search_resp[0] == 200 and control_resp[0] == 400:
        print("VERDICT: DEFECT_FOUND")
        print("EVIDENCE: params.hnsw_ef=0 returns 200 (should reject with 400)")
        print("CONTROL: params.hnsw_ef=-1 correctly returns 400")
        print(f"SEARCH_RESPONSE: {search_resp[2][:200]}")
        print(f"CONTROL_RESPONSE: {control_resp[2][:200]}")
    elif search_resp[0] == 400:
        print("VERDICT: NO_DEFECT")
        print("EVIDENCE: params.hnsw_ef=0 correctly rejected with 400")
    else:
        print(f"VERDICT: INCONCLUSIVE")
        print(f"SEARCH_STATUS: {search_resp[0]}, CONTROL_STATUS: {control_resp[0]}")

if __name__ == "__main__":
    main()
