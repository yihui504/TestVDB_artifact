#!/usr/bin/env python3
"""
Attack: Verify error message quality for invalid vectors.size=0 (should be positive integer)
Strategy: diagnosis_quality
Endpoint: collections+create
Constraint: qdrant_type_create_collection_001 (vectors.size must be positive integer)
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
    """
    Type-2 diagnosis quality rubric (3-point max):
    - 1pt: Mentions parameter name
    - 1pt: Indicates format/range
    - 1pt: Provides actionable suggestion
    """
    error_msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()
    score = 0
    if expected_param.lower() in error_msg:
        score += 1
    format_hints = ["must be", "expected", "should be", "valid", "range", "type", "positive", "greater than"]
    if any(hint in error_msg for hint in format_hints):
        score += 1
    action_hints = ["correct", "try", "use", "change", "specify", "provide"]
    if any(hint in error_msg for hint in action_hints):
        score += 1
    return score, 3

# Test: Create collection with vectors.size=0 (should be positive)
collection_name = "test_semantic_create_size_zero"
CREATE_PATH = f"/collections/{collection_name}"

# Cleanup first
try:
    safe_request("DELETE", f"/collections/{collection_name}")
except:
    pass

payload = {
    "vectors": {
        "size": 0,
        "distance": "Cosine"
    }
}

status, body, raw = safe_request("PUT", CREATE_PATH, json=payload)
print(f"Status: {status}")
print(f"Response: {raw[:500]}")

if status != 400:
    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — size=0 should be rejected with 400, got {status}")
    sys.exit(1)

# Check error quality
score, max_score = check_error_quality(status, body, "size")
print(f"Error Quality Score: {score}/{max_score}")

if score < 2:
    print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — Poor error message for invalid size=0 (score {score}/{max_score})")
    print("Expected: Should mention 'size' parameter and indicate it must be positive")
    sys.exit(1)

print("VERDICT: NO_DEFECT")

# Cleanup
try:
    safe_request("DELETE", f"/collections/{collection_name}")
except:
    pass
