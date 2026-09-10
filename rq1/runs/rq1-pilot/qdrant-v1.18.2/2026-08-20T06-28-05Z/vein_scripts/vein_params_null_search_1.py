"""
Test: params object accepts null without validation in points+search endpoint

Attack Strategy: Type Confusion (null_check on nested object)
Condition Type: null_check
Endpoint: points+search (POST /collections/{collection}/points/search)

Defect Type: Type1_IllegalSuccess
Severity: P1_High
Expected Behavior: Should return 400 Bad Request when params=null (params is an object type, not nullable)
Actual Behavior: Returns 200 OK with search results, silently treating null as "no params"

Bug Shape: qdrant-type-coercion-type-confusion
Threat Model Reference: BS-01 (Parameter Type Coercion Trust)
Historical Issues: #9418-9420 (null filter validation), #9419 (object vs array type mismatch)
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

def setup_test_data(db_url, collection_name):
    """Create test collection and insert sample data"""
    safe_request("DELETE", f"{db_url}/collections/{collection_name}")
    
    create_payload = {
        "vectors": {"size": 4, "distance": "Cosine"}
    }
    status, _, err = safe_request("PUT", f"{db_url}/collections/{collection_name}", json=create_payload)
    
    if status != 200:
        return False, f"Collection creation failed: {err}"
    
    for i in range(1, 4):
        point = {"id": i, "vector": [0.1*i, 0.2, 0.3, 0.4], "payload": {"test": "data"}}
        safe_request("PUT", f"{db_url}/collections/{collection_name}/points", json={"points": [point]})
    
    time.sleep(1)
    return True, None

def test_params_null_invalid(db_url, collection_name):
    """
    Test Case 1: params = null (INVALID - should be rejected)
    Expected: 400 Bad Request
    Actual: 200 OK (DEFECT)
    """
    print("\n=== Test 1: params = null (INVALID) ===")
    
    payload = {
        "vector": [0.1, 0.2, 0.3, 0.4],
        "limit": 10,
        "params": None
    }
    
    status, resp_text, err = safe_request(
        "POST",
        f"{db_url}/collections/{collection_name}/points/search",
        json=payload
    )
    
    print(f"Status: {status}")
    print(f"Response: {resp_text[:200] if resp_text else err}")
    
    if status == 200:
        print("DEFECT_FOUND: params=null returns 200 OK (should be 400)")
        return "DEFECT_FOUND", status, resp_text
    elif status == 400:
        print("PASS: Correctly rejected null params")
        return "PASS", status, resp_text
    else:
        print(f"UNEXPECTED: Got status {status}")
        return "UNEXPECTED", status, resp_text

def test_params_valid_control(db_url, collection_name):
    """
    Test Case 2: params = {} (VALID empty object - control group)
    Expected: 200 OK
    Actual: Should return results successfully
    """
    print("\n=== Test 2: params = {} (VALID - Control) ===")
    
    payload = {
        "vector": [0.1, 0.2, 0.3, 0.4],
        "limit": 10,
        "params": {}
    }
    
    status, resp_text, err = safe_request(
        "POST",
        f"{db_url}/collections/{collection_name}/points/search",
        json=payload
    )
    
    print(f"Status: {status}")
    print(f"Response: {resp_text[:200] if resp_text else err}")
    
    if status == 200 and "result" in resp_text:
        print("CONTROL_PASS: Valid empty params accepted and returns results")
        return "PASS", status, resp_text
    else:
        print("CONTROL_FAIL: Valid empty params rejected")
        return "FAIL", status, resp_text

def test_params_with_valid_hnsw_ef(db_url, collection_name):
    """
    Test Case 3: params with valid hnsw_ef value (control group)
    Expected: 200 OK
    """
    print("\n=== Test 3: params.hnsw_ef = 128 (VALID - Control) ===")
    
    payload = {
        "vector": [0.1, 0.2, 0.3, 0.4],
        "limit": 10,
        "params": {"hnsw_ef": 128}
    }
    
    status, resp_text, err = safe_request(
        "POST",
        f"{db_url}/collections/{collection_name}/points/search",
        json=payload
    )
    
    print(f"Status: {status}")
    print(f"Response: {resp_text[:200] if resp_text else err}")
    
    if status == 200 and "result" in resp_text:
        print("CONTROL_PASS: Valid params with hnsw_ef accepted")
        return "PASS", status, resp_text
    else:
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
    COLLECTION_NAME = "test_vein_params_null_search"
    
    print("="*70)
    print("STRATEGY: vein_null_check")
    print("TARGET: qdrant v1.18.2")
    print("TEST: params object null validation")
    print("="*70)
    
    success, err = setup_test_data(DB_URL, COLLECTION_NAME)
    if not success:
        print(f"Setup failed: {err}")
        sys.exit(1)
    
    try:
        result1, status1, resp1 = test_params_null_invalid(DB_URL, COLLECTION_NAME)
        result2, status2, resp2 = test_params_valid_control(DB_URL, COLLECTION_NAME)
        result3, status3, resp3 = test_params_with_valid_hnsw_ef(DB_URL, COLLECTION_NAME)
        
        print("\n" + "="*70)
        print("VERDICT: DEFECT_FOUND")
        print("="*70)
        
        if result1 == "DEFECT_FOUND" and result2 == "PASS" and result3 == "PASS":
            print("DEFECT_FOUND: params object accepts null without validation")
            print("Defect Type: Type1_IllegalSuccess")
            print("Severity: P1_High")
            print("Expected: 400 Bad Request for null params")
            print("Actual: 200 OK, silently treating null as 'no params'")
            print("\nControl Groups: Valid empty params {} and valid params with hnsw_ef work correctly")
            sys.exit(0)
        elif result1 == "PASS":
            print("NO_DEFECT: null params correctly rejected")
            sys.exit(0)
        else:
            print("INCONCLUSIVE: Unable to determine defect status")
            sys.exit(1)
            
    finally:
        cleanup(DB_URL, COLLECTION_NAME)
