#!/usr/bin/env python3
"""
Attack: Illegal Rejection test - valid distance metric "Dot"
Strategy: illegal_rejection
Endpoint: collections+create
Constraint: qdrant_type_create_collection_002 (vectors.distance valid enum values)
ExpectedDefect: Type1_IllegalRejection
"""

import os
import sys
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

def safe_request(method, endpoint, json=None, timeout=10):
    """Safe HTTP request wrapper with unified error handling"""
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(method=method, url=url, json=json, headers=headers, timeout=timeout)
        return response.status_code, response.json(), response.text
    except Exception as e:
        return -1, str(e), str(e)

# Test: Create collection with all valid distance metrics
valid_metrics = ["Cosine", "Euclidean", "Dot", "Manhattan"]

for metric in valid_metrics:
    collection_name = f"test_semantic_create_valid_{metric.lower()}"
    CREATE_PATH = f"/collections/{collection_name}"

    # Cleanup first
    try:
        safe_request("DELETE", CREATE_PATH)
    except:
        pass

    payload = {
        "vectors": {
            "size": 128,
            "distance": metric
        }
    }

    status, body, raw = safe_request("PUT", CREATE_PATH, json=payload)
    print(f"Metric: {metric}, Status: {status}")

    if status != 200:
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection) — Valid distance metric '{metric}' rejected with status {status}")
        print(f"Response: {raw[:500]}")
        sys.exit(1)

    # Cleanup
    try:
        safe_request("DELETE", CREATE_PATH)
    except:
        pass

print("VERDICT: NO_DEFECT")
