"""
Semantic Attack: Error Diagnosis Quality - Invalid Collection Name
Strategy: diagnosis_quality
Target: chroma v1.5.9
Verifies: Error on invalid collection name must indicate naming constraints clearly
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
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(method=method, url=url, json=json, headers=headers, timeout=timeout)
        status_code = response.status_code
        raw_text = response.text
        try:
            body = response.json()
        except:
            body = raw_text
        return status_code, body, raw_text
    except Exception as e:
        return -1, str(e), str(e)

def check_error_quality(status, body, expected_param, expected_details):
    """
    Type-2 diagnosis quality rubric:
    1. Parameter named (1pt)
    2. Format/range hint (1pt)
    3. Actionable suggestion (1pt)
    """
    if status == 200:
        return 0, 3, "Request should have been rejected"

    error_msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()
    score = 0

    # Criterion 1: Parameter named
    if expected_param and expected_param.lower() in error_msg:
        score += 1

    # Criterion 2: Format/range hint
    format_hints = ["must be", "expected", "should be", "valid", "range", "type", "positive", "non-zero",
                     "non-empty", "cannot", "invalid", "constraint"]
    if any(hint in error_msg for hint in format_hints):
        score += 1

    # Criterion 3: Actionable suggestion
    action_hints = ["correct", "try", "use", "change", "specify", "provide", "ensure", "make"]
    if any(hint in error_msg for hint in action_hints):
        score += 1

    return score, 3, error_msg

# Test 1: Empty collection name
status, body, raw = safe_request("POST", "/api/v1/collections/", json={})
print(f"Test 1 (empty collection name): status={status}")
print(raw)

score, max_score, msg = check_error_quality(body, "name", "collection")
print(f"Error quality: {score}/{max_score}")
if score < 2:
    print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — Poor error message for empty name (score={score}/3)")
    sys.exit(1)

# Test 2: Collection name with special characters (if invalid)
special_names = [
    "test/collection",  # slash
    "test collection",   # space
    "",                  # empty
    "test\x00collection", # null byte
]

for test_name in special_names:
    print(f"\nTesting invalid name: {repr(test_name)}")
    if test_name == "":
        # Skip empty as already tested
        continue

    # Try to create with invalid name
    status, body, raw = safe_request("POST", f"/api/v1/collections/{test_name}", json={})
    print(f"status={status}")
    print(raw[:200])

    if status in (200, 201):
        # If it succeeds, that's OK - just means the name is valid
        # Cleanup
        try:
            safe_request("DELETE", f"/api/v1/collections/{test_name}")
        except:
            pass
    elif status != 200:
        score, max_score, _ = check_error_quality(body, "name", "collection")
        print(f"Error quality: {score}/{max_score}")
        if score < 2 and score > 0:  # Only flag if error was returned but poor quality
            print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — Poor error for invalid name {repr(test_name)}")
            sys.exit(1)

# Test 3: Get non-existent collection
status, body, raw = safe_request("GET", "/api/v1/collections/definitely_not_exists_12345")
print(f"\nTest 3 (get non-existent collection): status={status}")
print(raw)

score, max_score, _ = check_error_quality(body, "collection", "not found")
print(f"Error quality: {score}/{max_score}")
if status != 404 and status != 200:
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Wrong status code for non-existent collection")
    sys.exit(1)

if status == 404:
    # Check error quality for 404
    if score < 1:
        print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — 404 error message unclear")
        sys.exit(1)

# Test 4: Add documents to non-existent collection
status, body, raw = safe_request("POST", "/api/v1/collections/nonexistent/add", json={
    "documents": ["test"],
    "embeddings": [[0.1]*384],
    "ids": ["test1"]
})
print(f"\nTest 4 (add to non-existent collection): status={status}")
print(raw)

score, max_score, _ = check_error_quality(body, "collection", "not found")
print(f"Error quality: {score}/{max_score}")
if status != 404 and status != 400:
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Wrong status for add to non-existent collection")
    sys.exit(1)

if score < 1:
    print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — Poor error for add to non-existent collection")
    sys.exit(1)

print("VERDICT: NO_DEFECT")
