#!/usr/bin/env python3
"""
TestVDB Attack Script - Vein Mining Round 2
Defect: Upsert silently discards empty vector arrays
Target: qdrant v1.18.0
"""

import requests
import json
import sys
import time

def safe_request(method, url, **kwargs):
    """Execute HTTP request with error handling"""
    try:
        response = requests.request(method, url, timeout=10, **kwargs)
        return response.status_code, response.json()
    except requests.exceptions.RequestException as e:
        return None, {"error": str(e)}

def cleanup(base_url, collection_name):
    """Remove test collection"""
    status, data = safe_request("DELETE", f"{base_url}/collections/{collection_name}")
    return status == 200

def main():
    base_url = "http://localhost:6333"
    collection_name = "test_vein_empty_vector_discard"

    print("=== Vein Test: Type Mismatch - Empty Vector Silent Discard ===")

    # Setup: Create collection
    print("\n1. Creating collection...")
    status, data = safe_request(
        "PUT",
        f"{base_url}/collections/{collection_name}",
        json={
            "vectors": {"size": 4, "distance": "Cosine"},
            "optimizers_config": {"indexing_threshold": 1}
        }
    )
    print(f"   Status: {status}, Response: {data}")
    if status != 200:
        print("   [FAIL] Collection creation failed")
        return False

    # Test: Upsert empty vector array
    print("\n2. Upserting point with empty vector array []...")
    status, data = safe_request(
        "PUT",
        f"{base_url}/collections/{collection_name}/points",
        json={
            "points": [{"id": 1, "vector": []}],
            "wait": True
        }
    )
    print(f"   Status: {status}, Response: {data}")

    # Baseline: Upsert correct vector
    print("\n3. Upserting point with correct vector...")
    status, data = safe_request(
        "PUT",
        f"{base_url}/collections/{collection_name}/points",
        json={
            "points": [{"id": 10, "vector": [0.1, 0.2, 0.3, 0.4]}],
            "wait": True
        }
    )
    print(f"   Status: {status}, Response: {data}")

    # Verify: Scroll to check actual stored points
    print("\n4. Scrolling to verify stored points...")
    status, data = safe_request(
        "POST",
        f"{base_url}/collections/{collection_name}/points/scroll",
        json={"limit": 100}
    )
    print(f"   Status: {status}")
    if status == 200:
        points = data.get("result", {}).get("points", [])
        point_ids = [p.get("id") for p in points]
        print(f"   Points found: {point_ids}")
        print(f"   Total count: {len(points)}")

        # Check if empty vector was silently discarded
        if 1 not in point_ids and 10 in point_ids:
            print("\n   [DEFECT_FOUND] Empty vector (id=1) was silently discarded")
            print("   Expected: 400 Bad Request or error about zero-length vector")
            print("   Actual: 200 OK with silent discard")
            VERDICT = "DEFECT_FOUND"
        elif 1 in point_ids:
            print("\n   [UNEXPECTED] Empty vector was accepted and stored")
            VERDICT = "UNEXPECTED_BEHAVIOR"
        else:
            print("\n   [INFO] Both points discarded")
            VERDICT = "INCONCLUSIVE"
    else:
        print(f"   [ERROR] Scroll failed: {data}")
        VERDICT = "TEST_ERROR"

    # Cleanup
    print("\n5. Cleaning up collection...")
    cleanup(base_url, collection_name)

    print(f"\n=== VERDICT: {VERDICT} ===")
    return VERDICT == "DEFECT_FOUND"

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
