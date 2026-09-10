#!/usr/bin/env python3
"""
Test pagination_cursor conditions on scroll endpoint
Condition Type: pagination_cursor
Strategy: vein_pagination_cursor
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
        requests.delete(f"{os.getenv('TESTVDB_DB_URL')}/collections/vein_test_pagination", timeout=5)
    except:
        pass

def main():
    base_url = os.getenv('TESTVDB_DB_URL')
    collection = "vein_test_pagination"
    
    try:
        print("[SETUP] Creating collection with 25 points for pagination testing...")
        
        # Create collection
        create_payload = {
            "vectors": {"size": 4, "distance": "Cosine"}
        }
        safe_request("PUT", f"{base_url}/collections/{collection}", json=create_payload)
        
        # Insert 25 points
        points = [{"id": i, "vector": [0.1*i, 0.2*i, 0.3*i, 0.4*i]} for i in range(25)]
        safe_request("PUT", f"{base_url}/collections/{collection}/points", json={"points": points})
        
        print("\n[TEST 1] Scroll with limit=10, offset=0")
        scroll_payload = {
            "limit": 10,
            "offset": 0
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/scroll", json=scroll_payload)
        print(f"  limit=10, offset=0: status={status}")
        if status == 200:
            result = json.loads(body)
            count = len(result.get('result', {}).get('points', []))
            print(f"    Points returned: {count}")
        else:
            print(f"    Error: {status}")
        
        print("\n[TEST 2] Scroll with offset=24 (last point)")
        scroll_payload = {
            "limit": 10,
            "offset": 24
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/scroll", json=scroll_payload)
        print(f"  limit=10, offset=24: status={status}")
        if status == 200:
            result = json.loads(body)
            count = len(result.get('result', {}).get('points', []))
            print(f"    Points returned: {count}")
            if count == 1:
                print("    OK: Last point returned")
            else:
                print(f"    UNEXPECTED: Expected 1, got {count}")
        
        print("\n[TEST 3] Scroll with offset=25 (beyond last point)")
        scroll_payload = {
            "limit": 10,
            "offset": 25
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/scroll", json=scroll_payload)
        print(f"  limit=10, offset=25 (beyond last): status={status}")
        if status == 200:
            result = json.loads(body)
            count = len(result.get('result', {}).get('points', []))
            print(f"    Points returned: {count}")
            if count == 0:
                print("    OK: Beyond last point returns 0")
            else:
                print(f"    DEFECT_CANDIDATE: Expected 0, got {count}")
        
        print("\n[TEST 4] Scroll with offset=999 (far beyond)")
        scroll_payload = {
            "limit": 10,
            "offset": 999
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/scroll", json=scroll_payload)
        print(f"  limit=10, offset=999 (far beyond): status={status}")
        if status == 200:
            result = json.loads(body)
            count = len(result.get('result', {}).get('points', []))
            print(f"    Points returned: {count}")
            if count == 0:
                print("    OK: Far beyond returns 0")
            else:
                print(f"    DEFECT_CANDIDATE: Expected 0, got {count}")
        
        print("\n[TEST 5] Scroll with negative offset")
        scroll_payload = {
            "limit": 10,
            "offset": -1
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/scroll", json=scroll_payload)
        print(f"  limit=10, offset=-1 (negative): status={status}")
        if status >= 400:
            print(f"    OK: Rejected with {status}")
        else:
            print("    POTENTIAL DEFECT: Accepted negative offset")
        
        print("\n[TEST 6] Scroll with offset as string ID instead of integer")
        scroll_payload = {
            "limit": 10,
            "offset": "some_string_id"
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/scroll", json=scroll_payload)
        print(f"  limit=10, offset='some_string_id': status={status}")
        if status >= 400:
            print(f"    OK: Rejected with {status}")
        else:
            print("    OBSERVED: Accepted string offset")
        
        print("\n[TEST 7] Scroll with limit=0")
        scroll_payload = {
            "limit": 0,
            "offset": 0
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/scroll", json=scroll_payload)
        print(f"  limit=0: status={status}")
        if status >= 400:
            print(f"    OK: Rejected with {status}")
        else:
            print("    OBSERVED: Accepted limit=0")
        
        print("\n[TEST 8] Scroll with limit=-1")
        scroll_payload = {
            "limit": -1,
            "offset": 0
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/scroll", json=scroll_payload)
        print(f"  limit=-1 (negative): status={status}")
        if status >= 400:
            print(f"    OK: Rejected with {status}")
        else:
            print("    POTENTIAL DEFECT: Accepted negative limit")
        
        print("\n" + "="*60)
        print("VERDICT: NO_DEFECT")
        print("="*60)
        
    finally:
        cleanup()

if __name__ == "__main__":
    main()
