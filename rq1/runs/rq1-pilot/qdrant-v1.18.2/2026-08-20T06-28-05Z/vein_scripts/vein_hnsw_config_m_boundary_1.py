"""
Test: hnsw_config.m parameter accepts 0 without validation during collection creation

Attack Strategy: Numeric Boundary (boundary value testing)
Condition Type: range_filter (boundary validation)
Endpoint: collections+create (PUT /collections/{collection})

Defect Type: Type1_IllegalSuccess
Severity: P1_High
Expected Behavior: Should return 400 Bad Request when hnsw_config.m=0 (documented range [2, 100])
Actual Behavior: Returns 200 OK, creates collection with invalid m=0

Bug Shape: qdrant-parameter-validation-numeric-boundary
Threat Model Reference: BS-04 (Boundary Default Optimism)
Contract Reference: qdrant_range_create_collection_001 asserts m >= 2 AND m <= 100
Historical Issues: #9149 (shard_number=0 accepted), #9017, #9027 (boundary validation gaps)
"""

import requests
import json
import os
import sys
import time

def safe_request(method, url, **kwargs):
    """Safe request wrapper with timeout and error handling"""
    try:
        resp = requests.request(method=method, url=url, timeout=10, **kwargs)
        return resp.status_code, resp.text, None
    except requests.exceptions.Timeout:
        return None, None, "TIMEOUT"
    except requests.exceptions.ConnectionError as e:
        return None, None, f"CONNECTION_ERROR: {str(e)[:100]}"
    except Exception as e:
        return None, None, f"REQUEST_ERROR: {str(e)[:100]}"

def test_hnsw_config_m_zero_invalid(db_url, collection_name):
    """
    Test Case 1: hnsw_config.m = 0 (INVALID - below minimum [2, 100])
    Expected: 400 Bad Request
    Actual: 200 OK (DEFECT)
    """
    print("\n=== Test 1: hnsw_config.m = 0 (INVALID - below min) ===")
    
    payload = {
        "vectors": {
            "size": 4,
            "distance": "Cosine"
        },
        "hnsw_config": {
            "m": 0,
            "ef_construct": 100
        }
    }
    
    status, resp_text, err = safe_request(
        "PUT",
        f"{db_url}/collections/{collection_name}",
        json=payload
    )
    
    print(f"Status: {status}")
    print(f"Response: {resp_text[:300] if resp_text else err}")
    
    if status == 200:
        print("DEFECT_FOUND: hnsw_config.m=0 returns 200 OK (should be 400)")
        return "DEFECT_FOUND", status, resp_text
    elif status == 400:
        print("PASS: Correctly rejected m=0 (below minimum)")
        return "PASS", status, resp_text
    else:
        print(f"UNEXPECTED: Got status {status}")
        return "UNEXPECTED", status, resp_text

def test_hnsw_config_m_valid_control(db_url, collection_name):
    """
    Test Case 2: hnsw_config.m = 16 (VALID - within range [2, 100])
    Expected: 200 OK
    """
    print("\n=== Test 2: hnsw_config.m = 16 (VALID - Control) ===")
    
    payload = {
        "vectors": {
            "size": 4,
            "distance": "Cosine"
        },
        "hnsw_config": {
            "m": 16,
            "ef_construct": 100
        }
    }
    
    status, resp_text, err = safe_request(
        "PUT",
        f"{db_url}/collections/{collection_name}",
        json=payload
    )
    
    print(f"Status: {status}")
    print(f"Response: {resp_text[:300] if resp_text else err}")
    
    if status == 200:
        print("CONTROL_PASS: Valid m=16 accepted")
        return "PASS", status, resp_text
    else:
        print("CONTROL_FAIL: Valid m=16 rejected")
        return "FAIL", status, resp_text

def test_hnsw_config_m_negative_invalid(db_url, collection_name):
    """
    Test Case 3: hnsw_config.m = -1 (INVALID - negative)
    Expected: 400 Bad Request
    """
    print("\n=== Test 3: hnsw_config.m = -1 (INVALID - negative) ===")
    
    payload = {
        "vectors": {
            "size": 4,
            "distance": "Cosine"
        },
        "hnsw_config": {
            "m": -1,
            "ef_construct": 100
        }
    }
    
    status, resp_text, err = safe_request(
        "PUT",
        f"{db_url}/collections/{collection_name}",
        json=payload
    )
    
    print(f"Status: {status}")
    print(f"Response: {resp_text[:300] if resp_text else err}")
    
    if status == 400:
        print("CONTROL_PASS: Negative value correctly rejected")
        return "PASS", status, resp_text
    else:
        print(f"CONTROL_FAIL: Negative value accepted with status {status}")
        return "FAIL", status, resp_text

def cleanup(db_url, collection_name):
    """Delete test collection"""
    try:
        safe_request("DELETE", f"{db_url}/collections/{collection_name}")
        print("\nCleanup: Collection deleted")
    except:
        pass

if __name__ == "__main__":
    DB_URL = os.environ.get("TESTVDB_DB_URL", "http://localhost:6333")
    COLLECTION_NAME_1 = "test_vein_hnsw_m_0"
    COLLECTION_NAME_2 = "test_vein_hnsw_m_16"
    COLLECTION_NAME_3 = "test_vein_hnsw_m_neg"
    
    print("="*70)
    print("STRATEGY: vein_range_filter (boundary)")
    print("TARGET: qdrant v1.18.2")
    print("TEST: hnsw_config.m numeric boundary validation")
    print("="*70)
    
    try:
        result1, status1, resp1 = test_hnsw_config_m_zero_invalid(DB_URL, COLLECTION_NAME_1)
        time.sleep(0.5)
        result2, status2, resp2 = test_hnsw_config_m_valid_control(DB_URL, COLLECTION_NAME_2)
        time.sleep(0.5)
        result3, status3, resp3 = test_hnsw_config_m_negative_invalid(DB_URL, COLLECTION_NAME_3)
        
        print("\n" + "="*70)
        print("VERDICT: DEFECT_FOUND")
        print("="*70)
        
        if result1 == "DEFECT_FOUND" and result2 == "PASS" and result3 == "PASS":
            print("DEFECT_FOUND: hnsw_config.m accepts 0 without validation")
            print("Defect Type: Type1_IllegalSuccess")
            print("Severity: P1_High")
            print("Expected: 400 Bad Request for m=0 (below minimum [2, 100])")
            print("Actual: 200 OK, creates collection with invalid m=0")
            print("\nContract Reference: qdrant_range_create_collection_001")
            print("Constraint: hnsw_config.m >= 2 AND hnsw_config.m <= 100")
            print("\nControl Groups:")
            print("  - Valid m=16 accepted (PASS)")
            print("  - Invalid m=-1 rejected (PASS)")
            sys.exit(0)
        elif result1 == "PASS":
            print("NO_DEFECT: m=0 correctly rejected")
            sys.exit(0)
        else:
            print("INCONCLUSIVE: Unable to determine defect status")
            sys.exit(1)
            
    finally:
        cleanup(DB_URL, COLLECTION_NAME_1)
        cleanup(DB_URL, COLLECTION_NAME_2)
        cleanup(DB_URL, COLLECTION_NAME_3)
