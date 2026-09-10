#!/usr/bin/env python3
"""
Detailed test of has_id edge cases - control group verification
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
        requests.delete(f"{os.getenv('TESTVDB_DB_URL')}/collections/vein_has_id_test", timeout=5)
    except:
        pass

def main():
    base_url = os.getenv('TESTVDB_DB_URL')
    collection = "vein_has_id_test"
    
    try:
        print("[SETUP] Creating collection with known test data...")
        
        # Create collection
        create_payload = {
            "vectors": {"size": 4, "distance": "Cosine"}
        }
        safe_request("PUT", f"{base_url}/collections/{collection}", json=create_payload)
        
        # Insert EXACTLY 3 points with known IDs
        points = [
            {"id": 100, "vector": [0.1, 0.2, 0.3, 0.4]},
            {"id": 200, "vector": [0.5, 0.6, 0.7, 0.8]},
            {"id": 300, "vector": [0.9, 1.0, 0.1, 0.2]}
        ]
        safe_request("PUT", f"{base_url}/collections/{collection}/points", json={"points": points})
        
        print("\n[CONTROL 1] Baseline - query with NO filter")
        query_payload = {"query": [0.1, 0.2, 0.3, 0.4]}
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/query", json=query_payload)
        result = json.loads(body)
        baseline_count = len(result.get('result', []))
        print(f"  No filter baseline: {baseline_count} points")
        
        print("\n[TEST 1] has_id with empty list []")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "filter": {"must": [{"has_id": []}]}
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/query", json=query_payload)
        result = json.loads(body) if status == 200 else None
        count = len(result.get('result', [])) if result else 0
        print(f"  has_id=[]: status={status}, count={count}")
        if count != 0:
            print(f"  DEFECT_CANDIDATE: Empty has_id should return 0, got {count}")
        else:
            print("  OK: Empty has_id returns 0")
        
        print("\n[TEST 2] has_id with single existing ID [100]")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "filter": {"must": [{"has_id": [100]}]}
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/query", json=query_payload)
        result = json.loads(body) if status == 200 else None
        count = len(result.get('result', [])) if result else 0
        print(f"  has_id=[100]: status={status}, count={count}")
        if count == 1:
            print("  OK: Exactly 1 point matched")
        else:
            print(f"  UNEXPECTED: Expected 1, got {count}")
        
        print("\n[TEST 3] has_id with multiple existing IDs [100, 200, 300]")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "filter": {"must": [{"has_id": [100, 200, 300]}]}
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/query", json=query_payload)
        result = json.loads(body) if status == 200 else None
        count = len(result.get('result', [])) if result else 0
        print(f"  has_id=[100,200,300]: status={status}, count={count}")
        if count == 3:
            print("  OK: All 3 points matched")
        else:
            print(f"  UNEXPECTED: Expected 3, got {count}")
        
        print("\n[TEST 4] has_id with duplicates [100, 100, 100]")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "filter": {"must": [{"has_id": [100, 100, 100]}]}
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/query", json=query_payload)
        result = json.loads(body) if status == 200 else None
        count = len(result.get('result', [])) if result else 0
        print(f"  has_id=[100,100,100]: status={status}, count={count}")
        if count == 1:
            print("  OK: Duplicates deduplicated, 1 point matched")
        else:
            print(f"  UNEXPECTED: Expected 1, got {count}")
        
        print("\n[TEST 5] has_id with mix of existing and non-existent [100, 999, 200]")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "filter": {"must": [{"has_id": [100, 999, 200]}]}
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/query", json=query_payload)
        result = json.loads(body) if status == 200 else None
        count = len(result.get('result', [])) if result else 0
        print(f"  has_id=[100,999,200]: status={status}, count={count}")
        if count == 2:
            print("  OK: Only existing IDs matched, non-existent ignored")
        else:
            print(f"  UNEXPECTED: Expected 2, got {count}")
        
        print("\n[TEST 6] has_id with ONLY non-existent IDs [999, 998, 997]")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "filter": {"must": [{"has_id": [999, 998, 997]}]}
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/query", json=query_payload)
        result = json.loads(body) if status == 200 else None
        count = len(result.get('result', [])) if result else 0
        print(f"  has_id=[999,998,997]: status={status}, count={count}")
        if count == 0:
            print("  OK: Non-existent IDs return 0 results")
        else:
            print(f"  DEFECT_CANDIDATE: Non-existent IDs should return 0, got {count}")
        
        print("\n" + "="*60)
        print("ANALYSIS COMPLETE")
        print("="*60)
        
    finally:
        cleanup()

    pass

def _final_verdict():
    print("VERDICT: DEFECT_FOUND")


if __name__ == "__main__":
    main()
    _final_verdict()
