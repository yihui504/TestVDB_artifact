"""
Semantic Attack: Write-Read Consistency - Documents must be queryable immediately after add
Strategy: behavioral_contract
Target: chroma v1.5.9
Verifies: Documents must be visible within 1 second after being added
"""

import os
import sys
import requests
import time
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

# Setup: Create collection
coll_name = "test_immediate_query"
safe_request("DELETE", f"/api/v1/collections/{coll_name}")  # cleanup if exists
status, _, raw = safe_request("POST", f"/api/v1/collections/{coll_name}")
if status not in (200, 201):
    print(f"VERDICT: SCRIPT_ERROR — collection creation failed: {status}")
    sys.exit(2)

# Test: Add document then query immediately (within 1 second)
unique_id = f"test_doc_{int(time.time() * 1000)}"
test_embedding = [0.123] * 384
test_document = "immediate query test document"

# Add document
status, body, raw = safe_request("POST", f"/api/v1/collections/{coll_name}/add", json={
    "documents": [test_document],
    "embeddings": [test_embedding],
    "ids": [unique_id],
    "metadatas": [{"test": "immediate"}]
})
print(f"Add document: status={status}")
print(raw)

if status not in (200, 201):
    print("VERDICT: SCRIPT_ERROR — add failed")
    sys.exit(2)

# Query immediately (within 1 second)
time.sleep(0.5)  # wait 500ms
status, body, raw = safe_request("POST", f"/api/v1/collections/{coll_name}/query", json={
    "query_embeddings": [test_embedding],
    "n_results": 10
})
print(f"\nQuery after 500ms: status={status}")
print(raw)

if status != 200:
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Query failed after add")
    sys.exit(1)

# Check that the added document is in results
results = body.get("results", [])
if not isinstance(results, list) or len(results) == 0:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — No results after immediate query")
    sys.exit(1)

first_result = results[0]
found_ids = [doc.get("id") for doc in first_result if isinstance(doc, dict) and "id" in doc]

if unique_id not in found_ids:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Document {unique_id} not found in immediate query")
    print(f"Found IDs: {found_ids}")
    sys.exit(1)

# Test 2: Add multiple documents and verify all are immediately queryable
second_id = f"test_doc_{int(time.time() * 1000)}_2"
status, _, raw = safe_request("POST", f"/api/v1/collections/{coll_name}/add", json={
    "documents": ["second doc"],
    "embeddings": [[0.456] * 384],
    "ids": [second_id],
    "metadatas": [{"test": "immediate_2"}]
})

if status not in (200, 201):
    print("VERDICT: SCRIPT_ERROR — second add failed")
    sys.exit(2)

# Query again after 500ms
time.sleep(0.5)
status, body, raw = safe_request("POST", f"/api/v1/collections/{coll_name}/get", json={
    "ids": [unique_id, second_id],
    "limit": 10
})
print(f"\nGet both docs after 500ms: status={status}")
print(raw)

if status != 200:
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Get failed after second add")
    sys.exit(1)

# Verify both documents present
if isinstance(body, list):
    found_ids = [doc.get("id") for doc in body if isinstance(doc, dict)]
else:
    found_ids = [doc.get("id") for doc in body.get("documents", []) if isinstance(doc, dict)]

if unique_id not in found_ids or second_id not in found_ids:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Not all documents found after immediate query")
    print(f"Expected: [{unique_id}, {second_id}], Found: {found_ids}")
    sys.exit(1)

# Cleanup
try:
    safe_request("DELETE", f"/api/v1/collections/{coll_name}")
except:
    pass

print("VERDICT: NO_DEFECT")
