"""
TestVDB Attack Script - Vein Mining (batch ordering validation)
Target: qdrant v1.18.2
Strategy: vein_params_semantic
Condition: ordering parameter validation in POST /points/batch
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
    collection = "vein_test_batch_ordering"

    # Setup: Create collection
    safe_request("DELETE", f"{db_url}/collections/{collection}")
    create_resp = safe_request("PUT", f"{db_url}/collections/{collection}",
        json={"vectors": {"size": 4, "distance": "Cosine"}})

    if create_resp[0] != 200:
        print(f"SETUP_FAILED: Could not create collection")
        return

    # Test: Batch with invalid ordering value
    batch_resp = safe_request("POST", f"{db_url}/collections/{collection}/points/batch",
        json={"operations": [
            {"upsert": {"points": [{"id": 1, "vector": [1.0, 0.0, 0.0, 0.0]}]}}
        ], "ordering": "invalid_value"})

    # Control group: Verify valid ordering values work
    control_weak = safe_request("POST", f"{db_url}/collections/{collection}/points/batch",
        json={"operations": [
            {"upsert": {"points": [{"id": 2, "vector": [0.0, 1.0, 0.0, 0.0]}]}}
        ], "ordering": "weak"})

    control_strong = safe_request("POST", f"{db_url}/collections/{collection}/points/batch",
        json={"operations": [
            {"upsert": {"points": [{"id": 3, "vector": [0.0, 0.0, 1.0, 0.0]}]}}
        ], "ordering": "strong"})

    # Cleanup
    safe_request("DELETE", f"{db_url}/collections/{collection}")

    # Analysis
    if batch_resp[0] == 200 and control_weak[0] == 200 and control_strong[0] == 200:
        print("VERDICT: DEFECT_FOUND")
        print("EVIDENCE: Invalid ordering='invalid_value' returns 200 (should reject with 400)")
        print("CONTROL: ordering='weak' and 'strong' correctly return 200")
        print(f"TEST_RESPONSE: {batch_resp[2][:200]}")
    elif batch_resp[0] == 400:
        print("VERDICT: NO_DEFECT")
        print("EVIDENCE: Invalid ordering correctly rejected with 400")
    else:
        print(f"VERDICT: INCONCLUSIVE")
        print(f"TEST_STATUS: {batch_resp[0]}, WEAK_STATUS: {control_weak[0]}, STRONG_STATUS: {control_strong[0]}")

if __name__ == "__main__":
    main()
