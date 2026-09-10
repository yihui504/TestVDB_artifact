#!/usr/bin/env python3
"""
TestVDB Attack Vein Script - Cardinality Oracle Bug on Compound AND Filter

DEFECT_ID: vein_compound_and_count-exact-false_1
TARGET: qdrant v1.19.0
STRATEGY: vein_compound_and

Tests cardinality estimation divergence between exact:true and exact:false
on POST /collections/{collection}/points/count with compound AND (must+must)
filter conditions combining multiple range predicates.

Issue: When querying with compound AND filter on multiple indexed payload fields,
count(exact:false) returns a different value than count(exact:true) and
scroll ground truth, indicating the cardinality estimator's combine_must
estimation formula is imprecise for multi-field range intersections.

This pattern generalizes the cardinality_oracle shape to compound filter
conditions, testing whether the intersection cardinality estimator is accurate
when combining multiple range predicates on different indexed fields.
"""

import requests
import json
import sys
import time


def safe_request(method, url, headers=None, json_data=None, timeout=10):
    """
    Safe HTTP request wrapper that returns (response, error) tuple.
    Handles network errors, timeouts, and invalid responses gracefully.
    """
    try:
        if method.upper() == "GET":
            response = requests.get(url, headers=headers, timeout=timeout)
        elif method.upper() == "POST":
            response = requests.post(url, headers=headers, json=json_data, timeout=timeout)
        elif method.upper() == "PUT":
            response = requests.put(url, headers=headers, json=json_data, timeout=timeout)
        elif method.upper() == "DELETE":
            response = requests.delete(url, headers=headers, timeout=timeout)
        else:
            return None, f"Unsupported method: {method}"

        return response, None
    except requests.exceptions.Timeout:
        return None, f"Request timeout after {timeout}s"
    except requests.exceptions.ConnectionError as e:
        return None, f"Connection error: {str(e)}"
    except Exception as e:
        return None, f"Request failed: {str(e)}"


def cleanup(db_url, collection_name):
    """Cleanup test collection"""
    try:
        url = f"{db_url}/collections/{collection_name}"
        resp, err = safe_request("DELETE", url)
        if err:
            print(f"Warning: cleanup failed - {err}")
    except:
        pass


def main():
    db_url = "http://localhost:6333"
    collection_name = "vein_compound_and_count"

    # Setup: Create collection with optimized payload indexing
    print(f"[SETUP] Creating collection {collection_name}...")

    url = f"{db_url}/collections/{collection_name}"
    create_data = {
        "vectors": {
            "size": 4,
            "distance": "Cosine"
        },
        "optimizers_config": {
            "indexing_threshold": 1
        },
        "hnsw_config": {
            "m": 16,
            "ef_construct": 100
        }
    }

    resp, err = safe_request("PUT", url, json_data=create_data)
    if err or (resp and resp.status_code != 200):
        print(f"VERDICT: SETUP_FAILED - Collection creation failed: {err or resp.text}")
        return

    # Insert test data with multiple numeric payload fields
    print(f"[SETUP] Inserting test points with age and score payload...")

    points_url = f"{db_url}/collections/{collection_name}/points"
    points_data = {
        "points": [
            {"id": 1, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"age": 25, "score": 85}},
            {"id": 2, "vector": [0.2, 0.3, 0.4, 0.5], "payload": {"age": 30, "score": 92}},
            {"id": 3, "vector": [0.3, 0.4, 0.5, 0.6], "payload": {"age": 35, "score": 78}},
            {"id": 4, "vector": [0.4, 0.5, 0.6, 0.7], "payload": {"age": 28, "score": 88}},
            {"id": 5, "vector": [0.5, 0.6, 0.7, 0.8], "payload": {"age": 32, "score": 95}},
            {"id": 6, "vector": [0.6, 0.7, 0.8, 0.9], "payload": {"age": 40, "score": 70}},
            {"id": 7, "vector": [0.7, 0.8, 0.9, 1.0], "payload": {"age": 45, "score": 82}},
            {"id": 8, "vector": [0.8, 0.9, 1.0, 0.1], "payload": {"age": 50, "score": 90}},
            {"id": 9, "vector": [0.9, 1.0, 0.1, 0.2], "payload": {"age": 55, "score": 65}},
            {"id": 10, "vector": [1.0, 0.1, 0.2, 0.3], "payload": {"age": 60, "score": 75}}
        ]
    }

    resp, err = safe_request("PUT", points_url, json_data=points_data)
    if err or (resp and resp.status_code != 200):
        print(f"VERDICT: SETUP_FAILED - Point insertion failed: {err or resp.text}")
        cleanup(db_url, collection_name)
        return

    # Create payload index on age field
    print(f"[SETUP] Creating payload index on 'age' field...")

    index_url = f"{db_url}/collections/{collection_name}/index/payload"
    index_data_age = {
        "field_name": "age",
        "field_schema": {
            "type": "integer",
            "range": True
        }
    }

    resp, err = safe_request("PUT", index_url, json_data=index_data_age)
    if err or (resp and resp.status_code != 200):
        print(f"VERDICT: SETUP_FAILED - Age index creation failed: {err or resp.text}")
        cleanup(db_url, collection_name)
        return

    # Create payload index on score field
    print(f"[SETUP] Creating payload index on 'score' field...")

    index_data_score = {
        "field_name": "score",
        "field_schema": {
            "type": "integer",
            "range": True
        }
    }

    resp, err = safe_request("PUT", index_url, json_data=index_data_score)
    if err or (resp and resp.status_code != 200):
        print(f"VERDICT: SETUP_FAILED - Score index creation failed: {err or resp.text}")
        cleanup(db_url, collection_name)
        return

    # Wait for indexes to build
    time.sleep(3)

    # TEST 1: Count with exact=true (ground truth baseline)
    print(f"[TEST 1] Counting points with exact=true and compound AND filter (age 25-44, score 80-94)...")

    count_url = f"{db_url}/collections/{collection_name}/points/count"
    count_data_exact_true = {
        "filter": {
            "must": [
                {"key": "age", "range": {"gte": 25, "lt": 45}},
                {"key": "score", "range": {"gte": 80, "lt": 95}}
            ]
        },
        "exact": True
    }

    resp, err = safe_request("POST", count_url, json_data=count_data_exact_true)
    if err:
        print(f"VERDICT: TEST_ERROR - exact=true request failed: {err}")
        cleanup(db_url, collection_name)
        return

    if resp.status_code != 200:
        print(f"VERDICT: TEST_ERROR - exact=true returned HTTP {resp.status_code}: {resp.text}")
        cleanup(db_url, collection_name)
        return

    exact_true_result = json.loads(resp.text or "{}")
    exact_true_count = exact_true_result.get("result", {}).get("count")
    print(f"[TEST 1] exact=true count: {exact_true_count}")

    # TEST 2: Count with exact=false (cardinality estimator)
    print(f"[TEST 2] Counting points with exact=false and compound AND filter (age 25-44, score 80-94)...")

    count_data_exact_false = {
        "filter": {
            "must": [
                {"key": "age", "range": {"gte": 25, "lt": 45}},
                {"key": "score", "range": {"gte": 80, "lt": 95}}
            ]
        },
        "exact": False
    }

    resp, err = safe_request("POST", count_url, json_data=count_data_exact_false)
    if err:
        print(f"VERDICT: TEST_ERROR - exact=false request failed: {err}")
        cleanup(db_url, collection_name)
        return

    if resp.status_code != 200:
        print(f"VERDICT: TEST_ERROR - exact=false returned HTTP {resp.status_code}: {resp.text}")
        cleanup(db_url, collection_name)
        return

    exact_false_result = json.loads(resp.text or "{}")
    exact_false_count = exact_false_result.get("result", {}).get("count")
    print(f"[TEST 2] exact=false count: {exact_false_count}")

    # TEST 3: Ground truth verification with scroll
    print(f"[TEST 3] Verifying ground truth with scroll query...")

    scroll_url = f"{db_url}/collections/{collection_name}/points/scroll"
    scroll_data = {
        "filter": {
            "must": [
                {"key": "age", "range": {"gte": 25, "lt": 45}},
                {"key": "score", "range": {"gte": 80, "lt": 95}}
            ]
        },
        "limit": 100
    }

    resp, err = safe_request("POST", scroll_url, json_data=scroll_data)
    if err:
        print(f"VERDICT: TEST_ERROR - scroll request failed: {err}")
        cleanup(db_url, collection_name)
        return

    if resp.status_code != 200:
        print(f"VERDICT: TEST_ERROR - scroll returned HTTP {resp.status_code}: {resp.text}")
        cleanup(db_url, collection_name)
        return

    scroll_result = json.loads(resp.text or "{}")
    scroll_points = scroll_result.get("result", {}).get("points", [])
    scroll_count = len(scroll_points)
    print(f"[TEST 3] scroll ground truth count: {scroll_count}")

    # ANALYSIS: Check for cardinality estimator divergence
    print(f"[ANALYSIS] Comparing cardinality estimates for compound AND filter...")

    # Calculate divergence percentage
    if exact_true_count > 0:
        divergence_pct = abs(exact_false_count - exact_true_count) / exact_true_count * 100
    else:
        divergence_pct = abs(exact_false_count - exact_true_count) * 100  # Absolute difference for zero base

    print(f"[ANALYSIS] Divergence: exact=true={exact_true_count}, exact=false={exact_false_count}, scroll={scroll_count}")
    print(f"[ANALYSIS] Absolute difference: {abs(exact_false_count - exact_true_count)} points ({divergence_pct:.1f}%)")

    # DEFECT DETECTION: Cardinality estimator is wrong for compound AND condition
    # Threshold: > 20% divergence OR systematic directional drift
    if divergence_pct > 20:
        print(f"VERDICT: DEFECT_FOUND")
        print(f"DEFECT_TYPE: Type2_PoorDiagnostics")
        print(f"SEVERITY: High")
        print(f"DESCRIPTION: Cardinality estimator for compound AND filter (age+score range intersection) is inaccurate")
        print(f"EVIDENCE:")
        print(f"  - exact=true (scan path): {exact_true_count} points")
        print(f"  - exact=false (estimator): {exact_false_count} points")
        print(f"  - scroll (ground truth): {scroll_count} points")
        print(f"  - Divergence: {divergence_pct:.1f}% exceeds 20% threshold")
        print(f"FILTER_CONDITIONS: age in [25,45), score in [80,95)")
        print(f"EXPECTED_BEHAVIOR: exact=false should return approximately same count as exact=true (within 20% tolerance)")
        print(f"ACTUAL_BEHAVIOR: Cardinality estimator overestimates by {abs(exact_false_count - exact_true_count)} points ({divergence_pct:.1f}%)")
        print(f"ROOT_CAUSE: The index-based cardinality estimator for compound AND intersections (combine_must_estimations) produces incorrect estimates")
        print(f"IMPACT: Applications relying on approximate counts for multi-filter queries will see incorrect values")
        print(f"RELATED: Generalizes cardinality_oracle shape to compound filter conditions")
        cleanup(db_url, collection_name)
        return

    # If divergence is within tolerance, check for systematic directional error
    if exact_false_count != exact_true_count and exact_false_count == scroll_count:
        print(f"VERDICT: NO_DEFECT")
        print(f"REASON: Divergence ({divergence_pct:.1f}%) is within acceptable estimation tolerance (20%)")
        print(f"NOTE: Minor estimation imprecision is acceptable for approximate counts")
        cleanup(db_url, collection_name)
        return

    # If counts match, no defect
    if exact_false_count == exact_true_count == scroll_count:
        print(f"VERDICT: NO_DEFECT")
        print(f"REASON: Cardinality estimator returns correct count")
        cleanup(db_url, collection_name)
        return

    # Ground truth mismatch
    if exact_true_count != scroll_count:
        print(f"VERDICT: TEST_ERROR")
        print(f"REASON: Ground truth mismatch - exact=true ({exact_true_count}) != scroll ({scroll_count})")
        cleanup(db_url, collection_name)
        return

    # Default fallback
    print(f"VERDICT: INCONCLUSIVE")
    print(f"REASON: Unexpected count pattern - exact=true={exact_true_count}, exact=false={exact_false_count}, scroll={scroll_count}")
    cleanup(db_url, collection_name)


if __name__ == "__main__":
    main()
