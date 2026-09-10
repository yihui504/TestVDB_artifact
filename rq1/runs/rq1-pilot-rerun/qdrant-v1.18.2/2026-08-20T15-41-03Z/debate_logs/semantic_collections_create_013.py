#!/usr/bin/env python3
"""
Attack: Diagnosis quality test - missing required vectors parameter
Strategy: diagnosis_quality
Endpoint: collections+create
Constraint: qdrant_type_create_collection_001 (vectors parameter required)
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

def check_error_quality(status, body, expected_param):
    """Type-2 diagnosis quality rubric"""
    error_msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()
    score = 0
    if expected_param.lower() in error_msg:
        score += 1
    required_hints = ["required", "must", "missing", "need"]
    if any(hint in error_msg for hint in required_hints):
        score += 1
    action_hints = ["provide", "specify", "include"]
    if any(hint in error_msg for hint in action_hints):
        score += 1
    return score, 3

# Test: Create collection without vectors parameter
collection_name = "test_semantic_create_no_vectors"
CREATE_PATH = f"/collections/{collection_name}"

# Cleanup first
try:
    safe_request("DELETE", f"/collections/{collection_name}")
except:
    pass

payload = {
    "hnsw_config": {
        "m": 16
    }
}

status, body, raw = safe_request("PUT", CREATE_PATH, json=payload)
print(f"Status: {status}")
print(f"Response: {raw[:500]}")

if status != 400:
    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Missing vectors should return 400, got {status}")
    sys.exit(1)

# Check error quality
score, max_score = check_error_quality(status, body, "vectors")
print(f"Error Quality Score: {score}/{max_score}")

if score < 2:
    print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — Poor error message for missing vectors (score {score}/{max_score})")
    print("Expected: Should mention 'vectors' is required")
    sys.exit(1)

print("VERDICT: NO_DEFECT")

# Cleanup
try:
    safe_request("DELETE", f"/collections/{collection_name}")
except:
    pass
