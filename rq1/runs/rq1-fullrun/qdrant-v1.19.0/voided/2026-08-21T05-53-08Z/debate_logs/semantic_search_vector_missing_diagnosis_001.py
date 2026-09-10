#!/usr/bin/env python3
"""
Attack: diagnosis_quality (qdrant_type_search_points_001 missing required vector)
Verifies error message quality when vector parameter is missing.
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
    """Safe HTTP request wrapper with unified error handling."""
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(method, url, json=json, headers=headers, timeout=timeout)
        status_code = response.status_code
        raw_text = response.text
        try:
            body = response.json()
        except:
            body = raw_text
        return status_code, body, raw_text
    except Exception as e:
        return -1, str(e), str(e)

def check_error_quality(status, body, expected_param):
    """Type-2 diagnosis quality rubric."""
    error_msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()
    score = 0
    max_score = 3

    if expected_param.lower() in error_msg:
        score += 1

    format_hints = ["required", "must be", "expected", "should be", "missing"]
    if any(hint in error_msg for hint in format_hints):
        score += 1

    action_hints = ["provide", "specify", "include", "add"]
    if any(hint in error_msg for hint in action_hints):
        score += 1

    return score, max_score

# Setup
COLLECTION_NAME = "test_search_missing_vector"
CREATE_PATH = f"/collections/{COLLECTION_NAME}"

try:
    safe_request("DELETE", CREATE_PATH)
except:
    pass

create_config = {"vectors": {"size": 128, "distance": "Cosine"}}
status, _, raw = safe_request("PUT", CREATE_PATH, json=create_config)
if status not in (200, 201):
    print(f"VERDICT: SCRIPT_ERROR — setup failed: {status}")
    sys.exit(2)

# Test: missing vector parameter
SEARCH_PATH = f"/collections/{COLLECTION_NAME}/points/search"

status, body, raw = safe_request("POST", SEARCH_PATH, json={"limit": 10})
print(raw)

score, max_score = check_error_quality(status, body, "vector")

if status == 200:
    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — missing vector should be rejected but got status=200")
    sys.exit(1)
elif status in (400, 422):
    if score < 2:
        print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — missing vector error quality {score}/{max_score}")
        sys.exit(1)
    else:
        print(f"VERDICT: NO_DEFECT — error message quality acceptable ({score}/{max_score})")
        sys.exit(0)
else:
    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — unexpected status {status} for missing vector")
    sys.exit(1)
