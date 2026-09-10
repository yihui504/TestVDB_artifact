#!/usr/bin/env python3
"""
Control group test for hnsw_ef=0 - verify this is not by-design
"""
import os
import sys
import json
import requests

def safe_request(method: str, url: str, **kwargs):
    resp = requests.request(method, url, timeout=10, **kwargs)
    return resp.status_code, resp.headers, resp.text

def cleanup():
    try:
        requests.delete(f"{os.getenv('TESTVDB_DB_URL')}/collections/vein_test_hnsw_control", timeout=5)
    except:
        pass

def main():
    base_url = os.getenv('TESTVDB_DB_URL')
    collection = "vein_test_hnsw_control"
    
    try:
        # Create collection with known valid hnsw_ef
        print("[CONTROL 1] Testing with valid hnsw_ef values")
        
        # Create collection
        create_payload = {
            "vectors": {"size": 4, "distance": "Cosine"}
        }
        status, _, _ = safe_request("PUT", f"{base_url}/collections/{collection}", json=create_payload)
        
        # Insert test points
        points = [{"id": i, "vector": [0.1*i, 0.2*i, 0.3*i, 0.4*i]} for i in range(5)]
        safe_request("PUT", f"{base_url}/collections/{collection}/points", json={"points": points})
        
        # Test with valid hnsw_ef values
        for ef_value in [10, 50, 100]:
            query_payload = {"query": [0.1, 0.2, 0.3, 0.4], "params": {"hnsw_ef": ef_value}}
            status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/query", json=query_payload)
            result = json.loads(body) if status == 200 else None
            count = len(result.get('result', [])) if result else 0
            print(f"  hnsw_ef={ef_value}: status={status}, result_count={count}")
        
        print("\n[CONTROL 2] Testing behavior difference with hnsw_ef=0")
        query_payload = {"query": [0.1, 0.2, 0.3, 0.4], "params": {"hnsw_ef": 0}}
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/query", json=query_payload)
        result = json.loads(body) if status == 200 else None
        count_0 = len(result.get('result', [])) if result else 0
        print(f"  hnsw_ef=0: status={status}, result_count={count_0}")
        
        # Compare with default (no params specified)
        query_payload = {"query": [0.1, 0.2, 0.3, 0.4]}
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/query", json=query_payload)
        result = json.loads(body) if status == 200 else None
        count_default = len(result.get('result', [])) if result else 0
        print(f"  default: status={status}, result_count={count_default}")
        
        print(f"\n[ANALYSIS]")
        if count_0 == count_default:
            print("  hnsw_ef=0 produces same results as default - may be valid alias")
        else:
            print(f"  hnsw_ef=0 produces DIFFERENT results ({count_0} vs {count_default}) - DEFECT_CANDIDATE")
        
        print("\n[CONTROL 3] Check HNSW config documentation expectations")
        print("  HNSW ef parameter typically should be >= 1 (represents ef-construction)")
        print("  Value of 0 would disable the search expansion - likely invalid")
        
    finally:
        cleanup()

if __name__ == "__main__":
    main()
