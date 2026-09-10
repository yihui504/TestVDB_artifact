"""
Semantic Attack: Empty Query Result Semantics
Strategy: behavioral_contract
Target: chroma v1.5.9
Verifies: Empty query results must be clearly indicated, not null/undefined
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

# Setup: Create collection and add documents with metadata
coll_name = "test_empty_results"
status, _, raw = safe_request("POST", f"/api/v1/collections/{coll_name}")
if status not in (200, 201):
    pass  # might exist

# Add documents with metadata
status, _, raw = safe_request("POST", f"/api/v1/collections/{coll_name}/add", json={
    "documents": ["doc1", "doc2", "doc3"],
    "embeddings": [[0.1]*384, [0.2]*384, [0.3]*384],
    "ids": ["id1", "id2", "id3"],
    "metadatas": [{"category": "A"}, {"category": "B"}, {"category": "A"}]
})
if status not in (200, 201):
    print(f"VERDICT: SCRIPT_ERROR — setup add failed: {status}")
    sys.exit(2)

# Test 1: Query with non-matching where filter (should return empty, not null)
status, body, raw = safe_request("POST", f"/api/v1/collections/{coll_name}/query", json={
    "query_embeddings": [[0.1]*384],
    "n_results": 10,
    "where": {"category": "NONEXISTENT"}
})
print(f"Test 1 (non-matching where): status={status}")
print(raw)

if status != 200:
    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Query with filter failed")
    sys.exit(1)

# Check response structure for empty results
results = body.get("results", [[]])
if not isinstance(results, list) or len(results) == 0:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — 'results' field missing or not list")
    sys.exit(1)

first_result = results[0] if len(results) > 0 else []
if first_result is None:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — First result is None/null")
    sys.exit(1)

if isinstance(first_result, list) and len(first_result) == 0:
    # Good: empty array
    pass
elif not isinstance(first_result, list):
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Result not a list: {type(first_result)}")
    sys.exit(1)

# Test 2: Query with where_document filter that matches nothing
status, body, raw = safe_request("POST", f"/api/v1/collections/{coll_name}/query", json={
    "query_embeddings": [[0.1]*384],
    "n_results": 10,
    "where_document": {"$contains": "never_in_any_doc"}
})
print(f"\nTest 2 (non-matching where_document): status={status}")
print(raw)

if status != 200:
    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Query with where_document failed")
    sys.exit(1)

results = body.get("results", [[]])
first_result = results[0] if len(results) > 0 else []
if first_result is None:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Null result for empty query")
    sys.exit(1)

# Test 3: Query with mismatching ID list (get operation)
status, body, raw = safe_request("POST", f"/api/v1/collections/{coll_name}/get", json={
    "ids": ["nonexistent_id_1", "nonexistent_id_2"],
    "limit": 10
})
print(f"\nTest 3 (get with non-existent IDs): status={status}")
print(raw)

if status != 200:
    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Get with non-existent IDs failed")
    sys.exit(1)

# For get operation, check that empty results is an empty array/list
documents = body if isinstance(body, list) else body.get("documents", body.get("results", []))
if documents is None:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Null for empty get result")
    sys.exit(1)
elif isinstance(documents, list) and len(documents) == 0:
    # Good: empty list
    pass
elif not isinstance(documents, list):
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Get result not list: {type(documents)}")
    sys.exit(1)

# Cleanup
try:
    safe_request("DELETE", f"/api/v1/collections/{coll_name}")
except:
    pass

print("VERDICT: NO_DEFECT")
