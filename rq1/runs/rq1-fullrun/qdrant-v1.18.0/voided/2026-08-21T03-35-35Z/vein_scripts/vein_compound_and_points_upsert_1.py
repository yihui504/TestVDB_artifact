#!/usr/bin/env python3
"""
TestVDB Attack Script - Vein Mining Round 2
Defect: Mixed batch upsert not atomic - invalid vectors prevent valid vectors from being inserted
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
    collection_name = "test_vein_mixed_batch_atomicity"

    print("=== Vein Test: Compound AND - Mixed Batch Non-Atomicity ===")

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

    # Test: Mixed batch - valid/invalid/valid vectors
    print("\n2. Upserting mixed batch: valid(dim4) / invalid(dim3) / valid(dim4)...")
    status, data = safe_request(
        "PUT",
        f"{base_url}/collections/{collection_name}/points",
        json={
            "points": [
                {"id": 30, "vector": [0.1, 0.2, 0.3, 0.4]},
                {"id": 31, "vector": [0.1, 0.2, 0.3]},
                {"id": 32, "vector": [0.5, 0.6, 0.7, 0.8]}
            ],
            "wait": True
        }
    )
    print(f"   Status: {status}, Response: {data}")

    # Verify: Scroll to check which points were stored
    print("\n3. Scrolling to verify stored points...")
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

        # Check atomicity violation
        # Expected: If atomic, either ALL or NONE should be inserted
        # Actual: Invalid point blocks valid points
        if 30 not in point_ids and 31 not in point_ids and 32 not in point_ids:
            print("\n   [DEFECT_FOUND] All points silently discarded (non-atomic)")
            print("   Expected: Per-point atomicity - valid points should be inserted")
            print("   Actual: One invalid point blocks entire batch")
            VERDICT = "DEFECT_FOUND"
        elif 30 not in point_ids and 32 not in point_ids and 31 not in point_ids:
            print("\n   [DEFECT_FOUND] Valid points (30, 32) not stored despite one invalid (31)")
            print("   Expected: Per-point atomicity")
            print("   Actual: Batch-level rejection")
            VERDICT = "DEFECT_FOUND"
        elif 30 in point_ids and 31 in point_ids and 32 in point_ids:
            print("\n   [UNEXPECTED] All points inserted including dimension-mismatched")
            VERDICT = "UNEXPECTED_BEHAVIOR"
        elif 30 in point_ids and 32 in point_ids and 31 not in point_ids:
            print("\n   [INFO] Per-point atomicity working (only valid points inserted)")
            VERDICT = "NO_DEFECT"
        elif 32 in point_ids and 30 not in point_ids:
            print(f"\n   [DEFECT_FOUND] Partial storage: same-batch valid points split (32 stored, 30 dropped)")
            VERDICT = "DEFECT_FOUND"
        else:
            print(f"\n   [INFO] Unexpected combination: {point_ids}")
            VERDICT = "INCONCLUSIVE"
    else:
        print(f"   [ERROR] Scroll failed: {data}")
        VERDICT = "TEST_ERROR"

    # Cleanup
    print("\n4. Cleaning up collection...")
    cleanup(base_url, collection_name)

    print(f"\n=== VERDICT: {VERDICT} ===")
    return VERDICT == "DEFECT_FOUND"

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
