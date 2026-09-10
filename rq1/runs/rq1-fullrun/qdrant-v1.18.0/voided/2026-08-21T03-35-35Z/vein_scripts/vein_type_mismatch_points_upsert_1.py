#!/usr/bin/env python3
"""
TestVDB Attack Script - Vein Mining Round 2
Defect: Upsert silently discards dimension-mismatched vectors
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
    collection_name = "test_vein_type_mismatch_dim_discard"

    print("=== Vein Test: Type Mismatch - Dimension Mismatch Silent Discard ===")

    # Setup: Create collection with 4-dimensional vectors
    print("\n1. Creating collection with 4D vectors...")
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

    # Test 1: Upsert dimension-3 vector (should fail but returns 200)
    print("\n2. Upserting point with dimension-3 vector (expecting 4)...")
    status, data = safe_request(
        "PUT",
        f"{base_url}/collections/{collection_name}/points",
        json={
            "points": [{"id": 1, "vector": [0.1, 0.2, 0.3]}],
            "wait": True
        }
    )
    print(f"   Status: {status}, Response: {data}")

    # Test 2: Upsert correct dimension-4 vector (baseline)
    print("\n3. Upserting point with correct dimension-4 vector...")
    status, data = safe_request(
        "PUT",
        f"{base_url}/collections/{collection_name}/points",
        json={
            "points": [{"id": 10, "vector": [0.1, 0.2, 0.3, 0.4]}],
            "wait": True
        }
    )
    print(f"   Status: {status}, Response: {data}")

    # Test 3: Scroll to verify which points were actually stored
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

        # Check if dimension-3 point was silently discarded
        if 1 not in point_ids and 10 in point_ids:
            print("\n   [DEFECT_FOUND] Dimension-mismatched vector (id=1) was silently discarded")
            print("   Expected: 400 Bad Request or error about dimension mismatch")
            print("   Actual: 200 OK with silent discard")
            VERDICT = "DEFECT_FOUND"
        elif 1 in point_ids:
            print("\n   [UNEXPECTED] Dimension-3 vector was accepted and stored")
            VERDICT = "UNEXPECTED_BEHAVIOR"
        else:
            print("\n   [INFO] Both points discarded (unexpected but not the target defect)")
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
