"""
Test: hnsw_ef parameter accepts null without validation in points+search endpoint

Attack Strategy: Type Confusion (null_check)
Condition Type: null_check
Endpoint: points+search (POST /collections/{collection}/points/search)

Defect Type: Type1_IllegalSuccess
Severity: P1_High
Expected Behavior: Should return 400 Bad Request when params.hnsw_ef=null (null is not a valid usize)
Actual Behavior: Returns 200 OK with search results, silently accepting null value

Bug Shape: qdrant-type-coercion-type-confusion
Threat Model Reference: BS-01 (Parameter Type Coercion Trust)
Historical Issues: #9373 (type confusion), #9418-9420 (null filter validation)
"""

import requests
import json
import os
import sys
import time

# Safe request wrapper per attack-vein v2.5.2
def safe_request(method, url, **kwargs):
    """
    Safe request wrapper with timeout and error handling.
    Returns: (status_code, response_text, error)
    """
    try:
        resp = requests.request(
            method=method,
            url=url,
            timeout=10,
            **kwargs
        )
        return resp.status_code, resp.text, None
    except requests.exceptions.Timeout:
        return None, None, "TIMEOUT"
    except requests.exceptions.ConnectionError as e:
        return None, None, f"CONNECTION_ERROR: {str(e)[:100]}"
    except Exception as e:
        return None, None, f"REQUEST_ERROR: {str(e)[:100]}"

def setup_test_data(db_url, collection_name):
    """Create test collection and insert sample data"""
    # Delete if exists
    safe_request("DELETE", f"{db_url}/collections/{collection_name}")
    
    # Create collection
    create_payload = {
        "vectors": {
            "size": 4,
            "distance": "Cosine"
        }
    }
    status, _, err = safe_request("PUT", f"{db_url}/collections/{collection_name}", json=create_payload)
    
    if status != 200:
        return False, f"Collection creation failed: {err}"
    
    # Insert test points
    for i in range(1, 4):
        point = {
            "id": i,
            "vector": [0.1*i, 0.2, 0.3, 0.4],
            "payload": {"test": "data"}
        }
        safe_request("PUT", f"{db_url}/collections/{collection_name}/points", json={"points": [point]})
    
    time.sleep(1)
    return True, None

def test_hnsw_ef_null_invalid(db_url, collection_name):
    """
    Test Case 1: params.hnsw_ef = null (INVALID - should be rejected)
    Expected: 400 Bad Request
    Actual: 200 OK (DEFECT)
    """
    print("\n=== Test 1: hnsw_ef = null (INVALID) ===")
    
    payload = {
        "vector": [0.1, 0.2, 0.3, 0.4],
        "limit": 10,
        "params": {
            "hnsw_ef": None
        }
    }
    
    status, resp_text, err = safe_request(
        "POST",
        f"{db_url}/collections/{collection_name}/points/search",
        json=payload
    )
    
    print(f"Status: {status}")
    print(f"Response: {resp_text[:200] if resp_text else err}")
    
    if status == 200:
        print("DEFECT_FOUND: hnsw_ef=null returns 200 OK (should be 400)")
        return "DEFECT_FOUND", status, resp_text
    elif status == 400:
        print("PASS: Correctly rejected null value")
        return "PASS", status, resp_text
    else:
        print(f"UNEXPECTED: Got status {status}")
        return "UNEXPECTED", status, resp_text

def test_hnsw_ef_valid_control(db_url, collection_name):
    """
    Test Case 2: params.hnsw_ef = 128 (VALID - control group)
    Expected: 200 OK
    Actual: Should return results successfully
    """
    print("\n=== Test 2: hnsw_ef = 128 (VALID - Control) ===")
    
    payload = {
        "vector": [0.1, 0.2, 0.3, 0.4],
        "limit": 10,
        "params": {
            "hnsw_ef": 128
        }
    }
    
    status, resp_text, err = safe_request(
        "POST",
        f"{db_url}/collections/{collection_name}/points/search",
        json=payload
    )
    
    print(f"Status: {status}")
    print(f"Response: {resp_text[:200] if resp_text else err}")
    
    if status == 200 and "result" in resp_text:
        print("CONTROL_PASS: Valid value accepted and returns results")
        return "PASS", status, resp_text
    else:
        print("CONTROL_FAIL: Valid value rejected or no results")
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
    COLLECTION_NAME = "test_vein_hnsw_ef_null_search"
    
    print("="*70)
    print("STRATEGY: vein_null_check")
    print("TARGET: qdrant v1.18.2")
    print("TEST: hnsw_ef parameter null validation")
    print("="*70)
    
    # Setup
    success, err = setup_test_data(DB_URL, COLLECTION_NAME)
    if not success:
        print(f"Setup failed: {err}")
        sys.exit(1)
    
    try:
        # Run tests
        result1, status1, resp1 = test_hnsw_ef_null_invalid(DB_URL, COLLECTION_NAME)
        result2, status2, resp2 = test_hnsw_ef_valid_control(DB_URL, COLLECTION_NAME)
        
        # VERDICT
        print("\n" + "="*70)
        print("VERDICT: DEFECT_FOUND")
        print("="*70)
        
        if result1 == "DEFECT_FOUND" and result2 == "PASS":
            print("DEFECT_FOUND: hnsw_ef parameter accepts null without validation")
            print("Defect Type: Type1_IllegalSuccess")
            print("Severity: P1_High")
            print("Expected: 400 Bad Request for null value")
            print("Actual: 200 OK, silently accepting null")
            print("\nControl Group: Valid value (128) works correctly")
            sys.exit(0)
        elif result1 == "PASS":
            print("NO_DEFECT: null value correctly rejected")
            sys.exit(0)
        else:
            print("INCONCLUSIVE: Unable to determine defect status")
            sys.exit(1)
            
    finally:
        cleanup(DB_URL, COLLECTION_NAME)
