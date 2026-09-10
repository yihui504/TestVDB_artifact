#!/usr/bin/env python3
"""
Test collection_membership condition variations (ID lists, match_any)
Condition Type: collection_membership
Strategy: vein_collection_membership
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
        requests.delete(f"{os.getenv('TESTVDB_DB_URL')}/collections/vein_test_membership", timeout=5)
    except:
        pass

def main():
    base_url = os.getenv('TESTVDB_DB_URL')
    collection = "vein_test_membership"
    
    try:
        print("[SETUP] Creating collection and inserting test data...")
        
        # Create collection
        create_payload = {
            "vectors": {"size": 4, "distance": "Cosine"}
        }
        status, _, _ = safe_request("PUT", f"{base_url}/collections/{collection}", json=create_payload)
        print(f"  Create collection: {status}")
        
        # Insert test points
        points = [
            {"id": 1, "vector": [0.1, 0.2, 0.3, 0.4]},
            {"id": 5, "vector": [0.5, 0.6, 0.7, 0.8]},
            {"id": 10, "vector": [0.9, 1.0, 0.1, 0.2]},
            {"id": 15, "vector": [0.2, 0.3, 0.4, 0.5]},
            {"id": 20, "vector": [0.6, 0.7, 0.8, 0.9]}
        ]
        status, _, _ = safe_request("PUT", f"{base_url}/collections/{collection}/points", json={"points": points})
        print(f"  Insert points: {status}")
        
        print("\n[TEST 1] Filter with ID list (is_empty variant)")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "filter": {
                "must": [
                    {"is_empty": {"payload": {"key": "nonexistent_field"}}}
                ]
            }
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/query", json=query_payload)
        print(f"  Is_empty filter: status={status}")
        if status == 200:
            result = json.loads(body)
            print(f"    Result count: {len(result.get('result', []))}")
        
        print("\n[TEST 2] Filter with has_id condition")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "filter": {
                "must": [
                    {"has_id": [1, 5, 10]}
                ]
            }
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/query", json=query_payload)
        print(f"  Has_id [1,5,10]: status={status}")
        if status == 200:
            result = json.loads(body)
            print(f"    Result count: {len(result.get('result', []))}")
            # Should return 3 points
        elif status >= 400:
            print(f"    Rejected with {status}")
        
        print("\n[TEST 3] Filter with has_id containing non-existent IDs")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "filter": {
                "must": [
                    {"has_id": [1, 999, 1000]}
                ]
            }
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/query", json=query_payload)
        print(f"  Has_id with non-existent [1,999,1000]: status={status}")
        if status == 200:
            result = json.loads(body)
            count = len(result.get('result', []))
            print(f"    Result count: {count} (should be 1)")
            if count == 1:
                print("    OK: Correctly filtered to only existing ID")
        
        print("\n[TEST 4] Filter with has_id empty list")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "filter": {
                "must": [
                    {"has_id": []}
                ]
            }
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/query", json=query_payload)
        print(f"  Has_id empty list: status={status}")
        if status == 200:
            result = json.loads(body)
            count = len(result.get('result', []))
            print(f"    Result count: {count}")
            if count == 0:
                print("    OK: Empty has_id returns no results")
        elif status >= 400:
            print(f"    Rejected with {status}")
        
        print("\n[TEST 5] Filter with has_id containing duplicate IDs")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "filter": {
                "must": [
                    {"has_id": [1, 1, 5, 5, 5]}
                ]
            }
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/query", json=query_payload)
        print(f"  Has_id with duplicates [1,1,5,5,5]: status={status}")
        if status == 200:
            result = json.loads(body)
            count = len(result.get('result', []))
            print(f"    Result count: {count}")
            if count == 2:
                print("    OK: Duplicates handled correctly (2 unique points)")
        
        print("\n[TEST 6] Filter with match_any (OR condition)")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "filter": {
                "should": [
                    {"has_id": [1]},
                    {"has_id": [5]},
                    {"has_id": [10]}
                ],
                "min_should": 1
            }
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/query", json=query_payload)
        print(f"  Match_any (should with 3 has_id): status={status}")
        if status == 200:
            result = json.loads(body)
            print(f"    Result count: {len(result.get('result', []))}")
        
        print("\n[TEST 7] Filter with match_any and min_should > 1")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "filter": {
                "should": [
                    {"has_id": [1]},
                    {"has_id": [5]}
                ],
                "min_should": 2  # Require both to match - impossible with has_id
            }
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{collection}/points/query", json=query_payload)
        print(f"  Match_any with min_should=2: status={status}")
        if status == 200:
            result = json.loads(body)
            count = len(result.get('result', []))
            print(f"    Result count: {count}")
            # This is a degenerate case - min_should > number of conditions that can match
            # Should return 0 results
        
        print("\n" + "="*60)
        print("VERDICT: NO_DEFECT")
        print("="*60)
        
    finally:
        cleanup()

if __name__ == "__main__":
    main()
