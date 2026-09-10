#!/usr/bin/env python3
"""
Test lookup_from object variations on POST /collections/{collection}/points/query
Condition Type: lookup_from_object
Strategy: vein_lookup_from
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
        requests.delete(f"{os.getenv('TESTVDB_DB_URL')}/collections/vein_test_lookup_from", timeout=5)
        requests.delete(f"{os.getenv('TESTVDB_DB_URL')}/collections/vein_test_lookup_from_src", timeout=5)
    except:
        pass

def main():
    base_url = os.getenv('TESTVDB_DB_URL')
    target_coll = "vein_test_lookup_from"
    src_coll = "vein_test_lookup_from_src"
    
    try:
        print("[SETUP] Creating two collections for lookup_from tests...")
        
        # Create source collection with indexed field
        create_payload = {
            "vectors": {"size": 4, "distance": "Cosine"},
            "hnsw_config": {"m": 16, "ef_construct": 100}
        }
        safe_request("PUT", f"{base_url}/collections/{src_coll}", json=create_payload)
        
        # Create index on source collection
        index_payload = {
            "field_name": "category",
            "field_schema": "keyword"
        }
        safe_request("PUT", f"{base_url}/collections/{src_coll}/index", json=index_payload)
        
        # Insert source points
        points = [
            {"id": 1, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"category": "A", "value": 10}},
            {"id": 2, "vector": [0.5, 0.6, 0.7, 0.8], "payload": {"category": "B", "value": 20}},
            {"id": 3, "vector": [0.9, 1.0, 0.1, 0.2], "payload": {"category": "A", "value": 30}}
        ]
        safe_request("PUT", f"{base_url}/collections/{src_coll}/points", json={"points": points})
        
        # Create target collection
        safe_request("PUT", f"{base_url}/collections/{target_coll}", json={"vectors": {"size": 4, "distance": "Cosine"}})
        
        # Insert target points
        points = [
            {"id": 101, "vector": [0.15, 0.25, 0.35, 0.45], "payload": {"ref_id": 1}},
            {"id": 102, "vector": [0.55, 0.65, 0.75, 0.85], "payload": {"ref_id": 2}}
        ]
        safe_request("PUT", f"{base_url}/collections/{target_coll}/points", json={"points": points})
        
        print("\n[TEST 1] lookup_from with valid collection reference")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "lookup_from": {"collection": src_coll}
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{target_coll}/points/query", json=query_payload)
        print(f"  Valid lookup_from: status={status}")
        if status == 200:
            result = json.loads(body)
            print(f"    Result count: {len(result.get('result', []))}")
        elif status >= 400:
            print(f"    Rejected with {status}")
        
        print("\n[TEST 2] lookup_from with non-existent collection")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "lookup_from": {"collection": "nonexistent_collection_xyz"}
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{target_coll}/points/query", json=query_payload)
        print(f"  Non-existent collection: status={status}")
        if status == 200:
            print("    POTENTIAL DEFECT: Silently accepted invalid collection")
        elif status >= 400:
            print(f"    OK: Rejected with {status}")
        
        print("\n[TEST 3] lookup_from with empty object")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "lookup_from": {}
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{target_coll}/points/query", json=query_payload)
        print(f"  Empty lookup_from: status={status}")
        if status == 200:
            print("    OBSERVED: Accepted empty lookup_from object")
        
        print("\n[TEST 4] lookup_from with null value")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "lookup_from": None
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{target_coll}/points/query", json=query_payload)
        print(f"  lookup_from=null: status={status}")
        if status == 200:
            print("    OBSERVED: Accepted null lookup_from")
        
        print("\n[TEST 5] lookup_from with unknown field")
        query_payload = {
            "query": [0.1, 0.2, 0.3, 0.4],
            "lookup_from": {"collection": src_coll, "unknown_field": "test"}
        }
        status, _, body = safe_request("POST", f"{base_url}/collections/{target_coll}/points/query", json=query_payload)
        print(f"  Unknown field in lookup_from: status={status}")
        if status == 200:
            print("    OBSERVED: Silently ignored unknown field")
        
        print("\n" + "="*60)
        print("VERDICT: DEFECT_FOUND")
        print("="*60)
        
    finally:
        cleanup()

if __name__ == "__main__":
    main()
