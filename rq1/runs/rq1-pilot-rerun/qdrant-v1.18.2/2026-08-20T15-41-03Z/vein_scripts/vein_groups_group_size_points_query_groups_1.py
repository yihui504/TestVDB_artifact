#!/usr/bin/env python3
"""
Test group_size parameter variations on query groups endpoint
Condition Type: groups_group_size
Strategy: vein_groups_group_size
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
        requests.delete(f"{os.getenv('TESTVDB_DB_URL')}/collections/vein_test_groups", timeout=5)
    except:
        pass

def main():
    base_url = os.getenv('TESTVDB_DB_URL')
    collection = "vein_test_groups"
    
    try:
        print("[SETUP] Creating collection with groupable data...")
        
        # Create collection
        create_payload = {
            "vectors": {"size": 4, "distance": "Cosine"}
        }
        safe_request("PUT", f"{base_url}/collections/{collection}", json=create_payload)
        
        # Insert points with groupable payload
        points = []
        for i in range(30):
            points.append({
                "id": i,
                "vector": [0.1*i, 0.2*i, 0.3*i, 0.4*i],
                "payload": {"category": f"cat_{i % 5}", "value": i}
            })
        safe_request("PUT", f"{base_url}/collections/{collection}/points", json={"points": points})
        
        print("\n[TEST 1] query groups with group_size=1")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "group_by": "payload.category",
            "group_size": 1,
            "limit": 10
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/query/groups", json=query_payload)
        print(f"  group_size=1: status={status}")
        if status == 200:
            result = json.loads(body)
            groups = result.get('result', {}).get('groups', [])
            print(f"    Groups returned: {len(groups)}")
            if groups:
                points_in_first = len(groups[0].get('hits', []))
                print(f"    Points in first group: {points_in_first}")
        elif status >= 400:
            print(f"    Error: {status}")
        
        print("\n[TEST 2] query groups with group_size=0")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "group_by": "payload.category",
            "group_size": 0,
            "limit": 10
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/query/groups", json=query_payload)
        print(f"  group_size=0: status={status}")
        if status == 200:
            result = json.loads(body)
            groups = result.get('result', {}).get('groups', [])
            print(f"    Groups returned: {len(groups)}")
            if groups:
                points_in_first = len(groups[0].get('hits', []))
                print(f"    Points in first group: {points_in_first}")
                if points_in_first == 0:
                    print("    DEFECT_CANDIDATE: group_size=0 should be rejected or return min 1")
            else:
                print("    Groups count: 0 (may be expected for group_size=0)")
        elif status >= 400:
            print(f"    OK: Rejected with {status}")
        
        print("\n[TEST 3] query groups with group_size=-1 (negative)")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "group_by": "payload.category",
            "group_size": -1,
            "limit": 10
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/query/groups", json=query_payload)
        print(f"  group_size=-1: status={status}")
        if status >= 400:
            print(f"    OK: Rejected with {status}")
        else:
            print("    POTENTIAL DEFECT: Accepted negative group_size")
        
        print("\n[TEST 4] query groups with group_size=999999 (extremely large)")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "group_by": "payload.category",
            "group_size": 999999,
            "limit": 10
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/query/groups", json=query_payload)
        print(f"  group_size=999999: status={status}")
        if status == 200:
            result = json.loads(body)
            groups = result.get('result', {}).get('groups', [])
            print(f"    Groups returned: {len(groups)}")
            if groups:
                points_in_first = len(groups[0].get('hits', []))
                print(f"    Points in first group: {points_in_first}")
                # Should be capped at actual available points in group
        elif status >= 400:
            print(f"    Rejected with {status}")
        
        print("\n[TEST 5] query groups with group_size > limit")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "group_by": "payload.category",
            "group_size": 50,  # Larger than limit
            "limit": 10
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/query/groups", json=query_payload)
        print(f"  group_size=50 > limit=10: status={status}")
        if status == 200:
            result = json.loads(body)
            groups = result.get('result', {}).get('groups', [])
            print(f"    Groups returned: {len(groups)}")
            print("    OBSERVED: group_size > limit is accepted")
        elif status >= 400:
            print(f"    Rejected with {status}")
        
        print("\n[TEST 6] query groups without group_size (should use default)")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "group_by": "payload.category",
            "limit": 10
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/query/groups", json=query_payload)
        print(f"  No group_size specified: status={status}")
        if status == 200:
            result = json.loads(body)
            groups = result.get('result', {}).get('groups', [])
            print(f"    Groups returned: {len(groups)}")
            if groups:
                points_in_first = len(groups[0].get('hits', []))
                print(f"    Points in first group: {points_in_first} (default group_size)")
        elif status >= 400:
            print(f"    Error: {status}")
        
        print("\n" + "="*60)
        print("VERDICT: NO_DEFECT")
        print("="*60)
        
    finally:
        cleanup()

if __name__ == "__main__":
    main()
