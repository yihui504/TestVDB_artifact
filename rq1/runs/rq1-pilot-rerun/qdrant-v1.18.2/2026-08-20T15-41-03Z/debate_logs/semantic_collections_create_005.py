#!/usr/bin/env python3
"""
Attack: Verify error message quality for indexing_threshold=-1 (below minimum 0)
Strategy: diagnosis_quality
Endpoint: collections+create
Constraint: qdrant_range_create_collection_003 (optimizers_config.indexing_threshold >= 0)
ExpectedDefect: Type2_PoorDiagnostics
"""

import os
import sys
import requests
import json

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

def check_error_quality(status, body, expected_param, range_min=None):
    """Type-2 diagnosis quality rubric"""
    error_msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()
    score = 0
    if expected_param.lower() in error_msg or "indexing_threshold" in error_msg.lower():
        score += 1
    range_hints = ["must be", "should be", "valid", "range", "minimum", "non-negative"]
    if any(hint in error_msg for hint in range_hints):
        score += 1
    if range_min is not None and str(range_min) in error_msg:
        score += 1
    return min(score, 3), 3

# Test: Create collection with indexing_threshold=-1
collection_name = "test_semantic_create_index_threshold_neg"
CREATE_PATH = f"/collections/{collection_name}"

# Cleanup first
try:
    safe_request("DELETE", f"/collections/{collection_name}")
except:
    pass

payload = {
    "vectors": {
        "size": 128,
        "distance": "Cosine"
    },
    "optimizers_config": {
        "indexing_threshold": -1
    }
}

status, body, raw = safe_request("PUT", CREATE_PATH, json=payload)
print(f"Status: {status}")
print(f"Response: {raw[:500]}")

if status != 400:
    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — indexing_threshold=-1 should be rejected with 400, got {status}")
    sys.exit(1)

# Check error quality
score, max_score = check_error_quality(status, body, "indexing_threshold", range_min=0)
print(f"Error Quality Score: {score}/{max_score}")

if score < 2:
    print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — Poor error message for indexing_threshold=-1 (score {score}/{max_score})")
    print("Expected: Should mention threshold must be non-negative (>= 0)")
    sys.exit(1)

print("VERDICT: NO_DEFECT")

# Cleanup
try:
    safe_request("DELETE", f"/collections/{collection_name}")
except:
    pass
