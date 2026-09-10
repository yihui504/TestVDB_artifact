#!/usr/bin/env python3
"""
Attack: diagnosis_quality (qdrant_type_search_points_001 vector dimension mismatch)
Verifies error message quality when query vector dimension doesn't match collection.
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

def check_error_quality(status, body, expected_terms):
    """Type-2 diagnosis quality rubric for dimension mismatch."""
    error_msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()
    score = 0
    max_score = 3

    # Criterion 1: Mention dimension or vector size
    if any(term.lower() in error_msg for term in expected_terms):
        score += 1

    # Criterion 2: Indicate collection dimension
    collection_hints = ["collection", "config", "size", "dimension", "expected"]
    if any(hint in error_msg for hint in collection_hints):
        score += 1

    # Criterion 3: Actionable suggestion
    action_hints = ["match", "use", "should be", "must be"]
    if any(hint in error_msg for hint in action_hints):
        score += 1

    return score, max_score

# Setup
COLLECTION_NAME = "test_search_dimension"
CREATE_PATH = f"/collections/{COLLECTION_NAME}"

try:
    safe_request("DELETE", CREATE_PATH)
except:
    pass

# Create collection with 128-dim vectors
create_config = {"vectors": {"size": 128, "distance": "Cosine"}}
status, _, raw = safe_request("PUT", CREATE_PATH, json=create_config)
if status not in (200, 201):
    print(f"VERDICT: SCRIPT_ERROR — setup failed: {status}")
    sys.exit(2)

# Test: query with 256-dim vector (dimension mismatch)
SEARCH_PATH = f"/collections/{COLLECTION_NAME}/points/search"
wrong_vector = [0.1] * 256

expected_terms = ["dimension", "size", "vector", "256", "128"]
status, body, raw = safe_request("POST", SEARCH_PATH, json={"vector": wrong_vector, "limit": 10})
print(raw)

score, max_score = check_error_quality(status, body, expected_terms)

if status == 200:
    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — dimension mismatch should be rejected but got status=200")
    sys.exit(1)
elif status in (400, 422):
    if score < 2:
        print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — dimension error quality {score}/{max_score}")
        print(f"Expected: mention dimension/vector size, indicate collection dimension (128), provide actionable suggestion")
        sys.exit(1)
    else:
        print(f"VERDICT: NO_DEFECT — error message quality acceptable ({score}/{max_score})")
        sys.exit(0)
else:
    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — unexpected status {status} for dimension mismatch")
    sys.exit(1)
