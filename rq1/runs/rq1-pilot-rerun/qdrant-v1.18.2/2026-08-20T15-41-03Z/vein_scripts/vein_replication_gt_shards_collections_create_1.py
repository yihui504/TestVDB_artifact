"""
TestVDB Attack Script - Vein Mining (distributed config semantic consistency)
Target: qdrant v1.18.2
Strategy: vein_config_semantic
Condition: replication_factor > shard_number semantic validation
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

    # Test 1: replication_factor=2, shard_number=1 (semantic invalidity)
    collection1 = "vein_test_repl_gt_shard"
    safe_request("DELETE", f"{db_url}/collections/{collection1}")

    test_resp = safe_request("PUT", f"{db_url}/collections/{collection1}",
        json={"vectors": {"size": 4, "distance": "Cosine"},
              "shard_number": 1,
              "replication_factor": 2})

    safe_request("DELETE", f"{db_url}/collections/{collection1}")

    # Control 1: Valid combination (replication_factor=1, shard_number=2)
    collection2 = "vein_test_valid_combo"
    safe_request("DELETE", f"{db_url}/collections/{collection2}")
    control_resp = safe_request("PUT", f"{db_url}/collections/{collection2}",
        json={"vectors": {"size": 4, "distance": "Cosine"},
              "shard_number": 2,
              "replication_factor": 1})
    safe_request("DELETE", f"{db_url}/collections/{collection2}")

    # Control 2: Equal values (replication_factor=1, shard_number=1)
    collection3 = "vein_test_equal_values"
    safe_request("DELETE", f"{db_url}/collections/{collection3}")
    control2_resp = safe_request("PUT", f"{db_url}/collections/{collection3}",
        json={"vectors": {"size": 4, "distance": "Cosine"},
              "shard_number": 1,
              "replication_factor": 1})
    safe_request("DELETE", f"{db_url}/collections/{collection3}")

    # Analysis
    if test_resp[0] == 200 and control_resp[0] == 200 and control2_resp[0] == 200:
        print("VERDICT: DEFECT_FOUND")
        print("EVIDENCE: replication_factor(2) > shard_number(1) returns 200 (semantically invalid)")
        print("CONTROL: Valid combinations (2>1, 1=1) correctly return 200")
        print(f"TEST_RESPONSE: {test_resp[2][:200]}")
    elif test_resp[0] == 400:
        print("VERDICT: NO_DEFECT")
        print("EVIDENCE: Semantic inconsistency correctly rejected with 400")
    else:
        print(f"VERDICT: INCONCLUSIVE")
        print(f"TEST_STATUS: {test_resp[0]}, CONTROL1_STATUS: {control_resp[0]}, CONTROL2_STATUS: {control2_resp[0]}")

if __name__ == "__main__":
    main()
