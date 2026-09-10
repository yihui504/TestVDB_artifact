#!/usr/bin/env python3
"""
TestVDB Attack Script - Vein Mining Round 2
Defect: Cardinality estimation over-counts on indexed numeric range filter
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
    collection_name = "test_vein_cardinality_numeric_range"

    print("=== Vein Test: Range Filter - Cardinality Estimation Bug ===")

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

    # Setup: Insert points with numeric scores
    print("\n2. Inserting points with numeric scores (10, 20, 30, 40, 50)...")
    points_data = [
        {"id": 300, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"score": 10}},
        {"id": 301, "vector": [0.2, 0.3, 0.4, 0.5], "payload": {"score": 20}},
        {"id": 302, "vector": [0.3, 0.4, 0.5, 0.6], "payload": {"score": 30}},
        {"id": 303, "vector": [0.4, 0.5, 0.6, 0.7], "payload": {"score": 40}},
        {"id": 304, "vector": [0.5, 0.6, 0.7, 0.8], "payload": {"score": 50}}
    ]
    status, data = safe_request(
        "PUT",
        f"{base_url}/collections/{collection_name}/points",
        json={"points": points_data, "wait": True}
    )
    print(f"   Status: {status}, Response: {data}")

    # Setup: Create numeric index
    print("\n3. Creating numeric index on 'score' field...")
    status, data = safe_request(
        "PUT",
        f"{base_url}/collections/{collection_name}/index",
        json={"field_name": "score", "field_schema": "integer"}
    )
    print(f"   Status: {status}, Response: {data}")
    print("   Waiting 3 seconds for index build...")
    time.sleep(3)

    # Test 1: Count with exact:true (ground truth - scan)
    print("\n4. Testing range filter (score >= 15 AND score <= 35)...")
    print("   [exact:true - scan path]")
    status, data = safe_request(
        "POST",
        f"{base_url}/collections/{collection_name}/points/count",
        json={
            "filter": {"must": [{"key": "score", "range": {"gte": 15, "lte": 35}}]},
            "exact": True
        }
    )
    print(f"   Status: {status}, Count(exact=true): {data.get('result', {}).get('count')}")
    count_exact = data.get("result", {}).get("count", 0) if status == 200 else 0

    # Test 2: Count with exact:false (estimation path)
    print("   [exact:false - estimation path]")
    status, data = safe_request(
        "POST",
        f"{base_url}/collections/{collection_name}/points/count",
        json={
            "filter": {"must": [{"key": "score", "range": {"gte": 15, "lte": 35}}]},
            "exact": False
        }
    )
    print(f"   Status: {status}, Count(exact=false): {data.get('result', {}).get('count')}")
    count_estimate = data.get("result", {}).get("count", 0) if status == 200 else 0

    # Test 3: Scroll ground truth
    print("   [scroll - ground truth]")
    status, data = safe_request(
        "POST",
        f"{base_url}/collections/{collection_name}/points/scroll",
        json={
            "filter": {"must": [{"key": "score", "range": {"gte": 15, "lte": 35}}]},
            "limit": 100
        }
    )
    scroll_count = 0
    if status == 200:
        points = data.get("result", {}).get("points", [])
        scroll_count = len(points)
        print(f"   Scroll ground truth: {scroll_count} points")
        point_ids = [p.get("id") for p in points]
        print(f"   Point IDs: {point_ids}")

    # Analyze: Check for estimation divergence
    print("\n5. Analyzing cardinality estimation accuracy...")
    if count_exact == scroll_count and count_estimate != scroll_count:
        divergence = abs(count_estimate - scroll_count)
        divergence_pct = (divergence / scroll_count) * 100 if scroll_count > 0 else 0
        print(f"   Ground truth (scroll): {scroll_count}")
        print(f"   Exact scan: {count_exact} ✓")
        print(f"   Estimation: {count_estimate} ✗")
        print(f"   Divergence: {divergence} points ({divergence_pct:.1f}%)")

        if count_estimate > count_exact:
            print("\n   [DEFECT_FOUND] Estimator OVER-counts (returns more than actual)")
            print("   This is a cardinality oracle bug in the numeric histogram estimator")
            VERDICT = "DEFECT_FOUND"
        else:
            print("\n   [DEFECT_FOUND] Estimator UNDER-counts (returns less than actual)")
            print("   This is a cardinality oracle bug in the numeric histogram estimator")
            VERDICT = "DEFECT_FOUND"
    elif count_exact == count_estimate == scroll_count:
        print(f"   All counts match at {scroll_count}")
        print("   [NO_DEFECT] Estimation accurate for this condition")
        VERDICT = "NO_DEFECT"
    else:
        print(f"   Unexpected pattern - exact:{count_exact} estimate:{count_estimate} scroll:{scroll_count}")
        VERDICT = "INCONCLUSIVE"

    # Cleanup
    print("\n6. Cleaning up collection...")
    cleanup(base_url, collection_name)

    print(f"\n=== VERDICT: {VERDICT} ===")
    return VERDICT == "DEFECT_FOUND"

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
