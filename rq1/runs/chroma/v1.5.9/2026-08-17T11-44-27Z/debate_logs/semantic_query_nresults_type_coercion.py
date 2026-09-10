"""
Semantic Attack: Type Coercion on query n_results parameter
Strategy: type_coercion
Target: chroma v1.5.9
"""

import os
import sys
import requests

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

def check_error_quality(status, body, expected_param):
    """Type-2 diagnosis quality: parameter name + format hint + actionable suggestion"""
    error_msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()
    score = 0
    if expected_param.lower() in error_msg:
        score += 1
    if any(hint in error_msg for hint in ["must be", "expected", "should be", "valid", "range", "type", "positive"]):
        score += 1
    if any(hint in error_msg for hint in ["correct", "try", "use", "change", "specify"]):
        score += 1
    return score, 3

# Setup: Create collection and add documents
coll_name = "test_query_nresults"
status, _, raw = safe_request("POST", f"/api/v1/collections/{coll_name}")
if status not in (200, 201):
    # Collection might exist, try to get it
    pass

# Add sample documents
status, _, raw = safe_request("POST", f"/api/v1/collections/{coll_name}/add", json={
    "documents": ["test doc 1", "test doc 2"],
    "embeddings": [[0.1]*384, [0.2]*384],
    "ids": ["doc1", "doc2"]
})
if status not in (200, 201):
    print(f"VERDICT: SCRIPT_ERROR — setup add failed: {status}")
    sys.exit(2)

# Test 1: String "10" instead of integer 10
status, body, raw = safe_request("POST", f"/api/v1/collections/{coll_name}/query", json={
    "query_embeddings": [[0.1]*384],
    "n_results": "10"
})
print(f"Test 1 (string '10'): status={status}")
print(raw)
if status == 200:
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — String '10' accepted as int n_results")
    sys.exit(1)

# Test 2: Float 10.0 instead of integer 10
status, body, raw = safe_request("POST", f"/api/v1/collections/{coll_name}/query", json={
    "query_embeddings": [[0.1]*384],
    "n_results": 10.0
})
print(f"Test 2 (float 10.0): status={status}")
print(raw)
if status == 200:
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — Float 10.0 accepted as int n_results")
    sys.exit(1)

# Test 3: Boolean true instead of integer
status, body, raw = safe_request("POST", f"/api/v1/collections/{coll_name}/query", json={
    "query_embeddings": [[0.1]*384],
    "n_results": True
})
print(f"Test 3 (boolean true): status={status}")
print(raw)
if status == 200:
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — Boolean true accepted as int n_results")
    sys.exit(1)

# Test 4: Negative integer (should be rejected with good error message)
status, body, raw = safe_request("POST", f"/api/v1/collections/{coll_name}/query", json={
    "query_embeddings": [[0.1]*384],
    "n_results": -5
})
print(f"Test 4 (negative -5): status={status}")
print(raw)
if status == 200:
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — Negative value accepted for n_results")
    sys.exit(1)

# Check error quality for rejection (if rejected)
if status != 200:
    score, max_score = check_error_quality(body, "n_results")
    print(f"Error quality score: {score}/{max_score}")
    if score < 2:
        print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — Poor error message for invalid n_results")
        sys.exit(1)

# Test 5: Zero value (should be rejected with good error message)
status, body, raw = safe_request("POST", f"/api/v1/collections/{coll_name}/query", json={
    "query_embeddings": [[0.1]*384],
    "n_results": 0
})
print(f"Test 5 (zero): status={status}")
print(raw)
if status == 200:
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — Zero accepted for n_results")
    sys.exit(1)

# Cleanup
try:
    safe_request("DELETE", f"/api/v1/collections/{coll_name}")
except:
    pass

print("VERDICT: NO_DEFECT")
