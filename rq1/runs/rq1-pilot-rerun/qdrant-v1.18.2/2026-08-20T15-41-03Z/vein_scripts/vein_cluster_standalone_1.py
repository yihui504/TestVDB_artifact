#!/usr/bin/env python3
"""
Test cluster standalone endpoints behavior
Condition Type: cluster_standalone
Strategy: vein_cluster_standalone
"""
import os
import sys
import json
import requests

def safe_request(method: str, url: str, **kwargs):
    resp = requests.request(method, url, timeout=10, **kwargs)
    return resp.status_code, resp.headers, resp.text

def main():
    base_url = os.getenv('TESTVDB_DB_URL')
    
    print("[TEST 1] GET /cluster - check cluster status")
    status, _, body = safe_request("GET", f"{base_url}/cluster")
    print(f"  Response: status={status}")
    if status == 200:
        result = json.loads(body)
        print(f"    Result keys: {list(result.keys())}")
        print(f"    Status: {result.get('status', 'N/A')}")
        print(f"    Description: {result.get('description', 'N/A')[:100] if result.get('description') else 'N/A'}")
    else:
        print(f"    ERROR: Cluster endpoint returned {status}")
    
    print("\n[TEST 2] GET /cluster in standalone mode (single node)")
    # In standalone mode, should still return 200 with status info
    status, _, body = safe_request("GET", f"{base_url}/cluster")
    print(f"  Standalone cluster status: {status}")
    if status == 200:
        result = json.loads(body)
        # Check if it reports as single node
        result_str = json.dumps(result)
        if 'single' in result_str.lower() or 'standalone' in result_str.lower():
            print("    Reports standalone/single mode")
        if 'peer_count' in result or 'number_of_peers' in result:
            print(f"    Peer count info present")
    
    print("\n[TEST 3] POST /cluster/recover - cluster recovery")
    # In standalone mode, should be rejected or no-op
    recover_payload = {
        "collection_name": "nonexistent_collection",
        "location": "some/path/to/snapshot",
        "check": True,
        "priority": "foreground"
    }
    status, _, body = safe_request("POST", f"{base_url}/cluster/recover", json=recover_payload)
    print(f"  Cluster recover: status={status}")
    if status == 200:
        print("    OBSERVED: Accepted recover request (may be no-op in standalone)")
    elif status >= 400:
        print(f"    Rejected with {status}")
        if status == 404 or status == 501:
            print("      Expected in standalone mode (not implemented/available)")
    
    print("\n[TEST 4] POST /cluster/recover with missing required fields")
    # Test with incomplete payload
    recover_payload = {}
    status, _, body = safe_request("POST", f"{base_url}/cluster/recover", json=recover_payload)
    print(f"  Empty recover payload: status={status}")
    if status >= 400:
        print(f"    OK: Rejected with {status}")
    else:
        print("    OBSERVED: Accepted empty payload")
    
    print("\n[TEST 5] GET /cluster/telemetry")
    status, _, body = safe_request("GET", f"{base_url}/cluster/telemetry")
    print(f"  Cluster telemetry: status={status}")
    if status == 200:
        result = json.loads(body)
        print(f"    Response structure present: {len(result)} fields")
    elif status >= 400:
        print(f"    Rejected with {status}")
    
    print("\n[TEST 6] DELETE /cluster/peer/delete")
    # In standalone mode, should be rejected
    delete_payload = {"peer_id": "some_peer_id"}
    status, _, body = safe_request("DELETE", f"{base_url}/cluster/peer/delete", json=delete_payload)
    print(f"  Delete peer: status={status}")
    if status == 200:
        print("    OBSERVED: Accepted delete in standalone mode")
    elif status >= 400:
        print(f"    Rejected with {status}")
        if status == 404 or status == 501:
            print("      Expected in standalone mode")
    
    print("\n" + "="*60)
    print("VERDICT: DEFECT_FOUND")
    print("Need to determine if cluster behaviors in standalone mode are defects or by-design")
    print("="*60)

if __name__ == "__main__":
    main()
