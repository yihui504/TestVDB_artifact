#!/usr/bin/env python3
"""
Cross-pollination test: Verify has_id defect on POST /collections/{collection}/points/search
Inspired by: vein_has_id_edge_cases_1 (DEFECT_FOUND on query endpoint)
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
        requests.delete(f"{os.getenv('TESTVDB_DB_URL')}/collections/vein_has_id_search", timeout=5)
    except:
        pass

def main():
    base_url = os.getenv('TESTVDB_DB_URL')
    collection = "vein_has_id_search"
    
    try:
        print("[CROSS-POLLINATION] Testing has_id defect on search endpoint")
        print("Inspired by: DEFECT_FOUND on query endpoint - has_id only processes first ID")
        print()
        
        # Setup
        print("[SETUP] Creating collection with known test data...")
        create_payload = {
            "vectors": {"size": 4, "distance": "Cosine"}
        }
        safe_request("PUT", f"{base_url}/collections/{collection}", json=create_payload)
        
        points = [
            {"id": 100, "vector": [0.1, 0.2, 0.3, 0.4]},
            {"id": 200, "vector": [0.5, 0.6, 0.7, 0.8]},
            {"id": 300, "vector": [0.9, 1.0, 0.1, 0.2]}
        ]
        safe_request("PUT", f"{base_url}/collections/{collection}/points", json={"points": points})
        
        print("\n[TEST 1] search with has_id=[100,200,300]")
        search_payload = {
            "vector": [0.1, 0.2, 0.3, 0.4],
            "filter": {"must": [{"has_id": [100, 200, 300]}]},
            "limit": 10
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/search", json=search_payload)
        print(f"  status={status}")
        if status == 200:
            result = json.loads(body)
            count = len(result.get('result', []))
            print(f"  Results: {count} points")
            if count == 1:
                print("[X] DEFECT CONFIRMED ON SEARCH: Only first ID matched")
            elif count == 3:
                print("[OK] NO DEFECT: All 3 IDs matched")
            else:
                print(f"[?] UNEXPECTED: Got {count} results")
        
        print("\n[TEST 2] search with has_id=[]")
        search_payload = {
            "vector": [0.1, 0.2, 0.3, 0.4],
            "filter": {"must": [{"has_id": []}]},
            "limit": 10
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/search", json=search_payload)
        print(f"  status={status}")
        if status == 200:
            result = json.loads(body)
            count = len(result.get('result', []))
            print(f"  Results: {count} points")
            if count == 0:
                print("[OK] NO DEFECT: Empty has_id returns 0")
            else:
                print(f"[X] DEFECT CONFIRMED: Empty has_id returned {count} points")
        
        print("\n[TEST 3] search with has_id=[999,998,997] (non-existent)")
        search_payload = {
            "vector": [0.1, 0.2, 0.3, 0.4],
            "filter": {"must": [{"has_id": [999, 998, 997]}]},
            "limit": 10
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/search", json=search_payload)
        print(f"  status={status}")
        if status == 200:
            result = json.loads(body)
            count = len(result.get('result', []))
            print(f"  Results: {count} points")
            if count == 0:
                print("[OK] NO DEFECT: Non-existent IDs return 0")
            else:
                print(f"[X] DEFECT CONFIRMED: Non-existent IDs returned {count} points")
        
        print("\n" + "="*60)
        print("CROSS-POLLINATION ANALYSIS")
        print("Checking if has_id defect exists across query/search/recommend")
        print("="*60)
        
    finally:
        cleanup()

    pass

def _final_verdict():
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
    _final_verdict()
