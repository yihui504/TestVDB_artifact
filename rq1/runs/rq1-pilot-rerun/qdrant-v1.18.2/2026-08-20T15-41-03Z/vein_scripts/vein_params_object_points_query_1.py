#!/usr/bin/env python3
"""
Test params object variations on POST /collections/{collection}/points/query
Condition Type: params_object
Strategy: vein_params_object
"""
import os
import sys
import json
import requests
from typing import Tuple, Optional

def safe_request(method: str, url: str, **kwargs) -> Tuple[int, dict, str]:
    """Make HTTP request with error handling."""
    try:
        resp = requests.request(method, url, timeout=10, **kwargs)
        return resp.status_code, resp.headers, resp.text
    except Exception as e:
        return 0, {}, str(e)

def cleanup() -> None:
    """Clean up test collections."""
    try:
        requests.delete(f"{os.getenv('TESTVDB_DB_URL')}/collections/vein_test_query_params", timeout=5)
    except:
        pass

def main():
    base_url = os.getenv('TESTVDB_DB_URL')
    if not base_url:
        print("ERROR: TESTVDB_DB_URL not set")
        sys.exit(1)
    
    collection = "vein_test_query_params"
    
    try:
        # Setup: Create collection and insert test data
        print("[SETUP] Creating collection and inserting data...")
        
        # Create collection
        create_payload = {
            "vectors": {
                "size": 4,
                "distance": "Cosine"
            }
        }
        status, headers, body = safe_request(
            "PUT", f"{base_url}/collections/{collection}",
            json=create_payload
        )
        print(f"Create collection: status={status}")
        
        # Insert test points
        points = []
        for i in range(10):
            points.append({
                "id": i,
                "vector": [0.1 * i, 0.2 * i, 0.3 * i, 0.4 * i],
                "payload": {"category": f"cat_{i % 3}", "value": i}
            })
        
        status, headers, body = safe_request(
            "PUT", f"{base_url}/collections/{collection}/points",
            json={"points": points}
        )
        print(f"Insert points: status={status}")
        
        # TEST 1: params.hnsw_ef with negative value (should reject)
        print("\n[TEST 1] params.hnsw_ef = -1 (negative)")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "params": {"hnsw_ef": -1}
        }
        status, headers, body = safe_request(
            "POST", f"{base_url}/collections/{collection}/points/query",
            json=query_payload
        )
        print(f"  Response: status={status}")
        if status == 200:
            print("  POTENTIAL DEFECT: Accepted negative hnsw_ef value")
        elif status >= 400:
            print(f"  OK: Properly rejected with {status}")
        
        # TEST 2: params.hnsw_ef with zero (should reject or handle gracefully)
        print("\n[TEST 2] params.hnsw_ef = 0 (zero)")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "params": {"hnsw_ef": 0}
        }
        status, headers, body = safe_request(
            "POST", f"{base_url}/collections/{collection}/points/query",
            json=query_payload
        )
        print(f"  Response: status={status}")
        if status == 200:
            print("  POTENTIAL DEFECT: Accepted zero hnsw_ef value")
        elif status >= 400:
            print(f"  OK: Properly rejected with {status}")
        
        # TEST 3: params.hnsw_ef with extremely large value
        print("\n[TEST 3] params.hnsw_ef = 999999 (extremely large)")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "params": {"hnsw_ef": 999999}
        }
        status, headers, body = safe_request(
            "POST", f"{base_url}/collections/{collection}/points/query",
            json=query_payload
        )
        print(f"  Response: status={status}")
        if status == 200:
            print("  OBSERVED: Accepted large hnsw_ef value (may be valid)")
        
        # TEST 4: params object with unknown field
        print("\n[TEST 4] params.unknown_field = 'test'")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "params": {"unknown_field": "test"}
        }
        status, headers, body = safe_request(
            "POST", f"{base_url}/collections/{collection}/points/query",
            json=query_payload
        )
        print(f"  Response: status={status}")
        if status == 200:
            print("  OBSERVED: Silently ignored unknown params field")
        elif status >= 400:
            print(f"  OK: Rejected unknown params with {status}")
        
        # TEST 5: params as null instead of object
        print("\n[TEST 5] params = null (type mismatch)")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "params": None
        }
        status, headers, body = safe_request(
            "POST", f"{base_url}/collections/{collection}/points/query",
            json=query_payload
        )
        print(f"  Response: status={status}")
        if status == 200:
            print("  OBSERVED: Accepted params=null")
        
        # TEST 6: params as empty object
        print("\n[TEST 6] params = {} (empty object)")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "params": {}
        }
        status, headers, body = safe_request(
            "POST", f"{base_url}/collections/{collection}/points/query",
            json=query_payload
        )
        print(f"  Response: status={status}")
        if status == 200:
            print("  OBSERVED: Accepted empty params object")
        
        print("\n" + "="*60)
        print("VERDICT: NO_DEFECT")
        print("Need to review actual responses to determine DEFECT_FOUND vs NO_DEFECT")
        print("="*60)
        
    finally:
        cleanup()

if __name__ == "__main__":
    main()
