"""
Semantic Attack: Metadata Filter Numeric Comparison Semantics
Strategy: filter_semantics
Target: chroma v1.5.9
Verifies: Metadata filtering must support numeric comparisons (>, >=, <, <=)
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

# Setup: Create collection
coll_name = "test_numeric_filter"
safe_request("DELETE", f"/api/v1/collections/{coll_name}")
status, _, raw = safe_request("POST", f"/api/v1/collections/{coll_name}")
if status not in (200, 201):
    print(f"VERDICT: SCRIPT_ERROR — collection creation failed: {status}")
    sys.exit(2)

# Add documents with numeric metadata
status, _, raw = safe_request("POST", f"/api/v1/collections/{coll_name}/add", json={
    "documents": [f"doc {i}" for i in range(5)],
    "embeddings": [[float(i)]*384 for i in range(5)],
    "ids": [f"doc{i}" for i in range(5)],
    "metadatas": [
        {"score": 10},
        {"score": 20},
        {"score": 30},
        {"score": 40},
        {"score": 50}
    ]
})
if status not in (200, 201):
    print(f"VERDICT: SCRIPT_ERROR — add failed: {status}")
    sys.exit(2)

# Test 1: Filter with > operator (score > 25)
status, body, raw = safe_request("POST", f"/api/v1/collections/{coll_name}/query", json={
    "query_embeddings": [[0.1]*384],
    "n_results": 10,
    "where": {"score": {"$gt": 25}}
})
print(f"Test 1 (score > 25): status={status}")
print(raw)

if status != 200:
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Numeric filter $gt failed")
    sys.exit(1)

# Should return 3 docs: doc3(30), doc4(40), doc5(50)
results = body.get("results", [[]])[0]
if not isinstance(results, list) or len(results) == 0:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — No results for $gt filter")
    sys.exit(1)

# Check count
result_ids = [r.get("id") for r in results if isinstance(r, dict) and "id" in r]
expected_ids = ["doc3", "doc4", "doc5"]
if len(result_ids) != 3:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Expected 3 results for score>25, got {len(result_ids)}")
    print(f"Expected: {expected_ids}, Got: {result_ids}")
    sys.exit(1)

# Verify correct IDs
if not all(eid in result_ids for eid in expected_ids):
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Wrong IDs in $gt filter results")
    print(f"Expected: {expected_ids}, Got: {result_ids}")
    sys.exit(1)

# Test 2: Filter with >= operator (score >= 30)
status, body, raw = safe_request("POST", f"/api/v1/collections/{coll_name}/query", json={
    "query_embeddings": [[0.1]*384],
    "n_results": 10,
    "where": {"score": {"$gte": 30}}
})
print(f"\nTest 2 (score >= 30): status={status}")
print(raw)

if status != 200:
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Numeric filter $gte failed")
    sys.exit(1)

# Should return 3 docs: doc3(30), doc4(40), doc5(50)
results = body.get("results", [[]])[0]
result_ids = [r.get("id") for r in results if isinstance(r, dict) and "id" in r]
if len(result_ids) != 3:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Expected 3 results for score>=30, got {len(result_ids)}")
    sys.exit(1)

# Test 3: Filter with < operator (score < 35)
status, body, raw = safe_request("POST", f"/api/v1/collections/{coll_name}/query", json={
    "query_embeddings": [[0.1]*384],
    "n_results": 10,
    "where": {"score": {"$lt": 35}}
})
print(f"\nTest 3 (score < 35): status={status}")
print(raw)

if status != 200:
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Numeric filter $lt failed")
    sys.exit(1)

# Should return 4 docs: doc0(10), doc1(20), doc2(30), doc3(40)
# Wait, 40 is NOT < 35, so should be doc0(10), doc1(20), doc2(30)
results = body.get("results", [[]])[0]
result_ids = [r.get("id") for r in results if isinstance(r, dict) and "id" in r]
expected_ids = ["doc0", "doc1", "doc2"]
if len(result_ids) != 3:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Expected 3 results for score<35, got {len(result_ids)}")
    print(f"Expected: {expected_ids}, Got: {result_ids}")
    sys.exit(1)

# Test 4: Filter with <= operator (score <= 30)
status, body, raw = safe_request("POST", f"/api/v1/collections/{coll_name}/query", json={
    "query_embeddings": [[0.1]*384],
    "n_results": 10,
    "where": {"score": {"$lte": 30}}
})
print(f"\nTest 4 (score <= 30): status={status}")
print(raw)

if status != 200:
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Numeric filter $lte failed")
    sys.exit(1)

# Should return 4 docs: doc0(10), doc1(20), doc2(30), doc3(40)
# Wait, 40 is NOT <= 30, so should be doc0(10), doc1(20), doc2(30)
results = body.get("results", [[]])[0]
result_ids = [r.get("id") for r in results if isinstance(r, dict) and "id" in r]
expected_ids = ["doc0", "doc1", "doc2"]
if len(result_ids) != 3:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Expected 3 results for score<=30, got {len(result_ids)}")
    sys.exit(1)

# Test 5: Range query (20 < score <= 40)
status, body, raw = safe_request("POST", f"/api/v1/collections/{coll_name}/query", json={
    "query_embeddings": [[0.1]*384],
    "n_results": 10,
    "where": {"$and": [{"score": {"$gt": 20}}, {"score": {"$lte": 40}}]}
})
print(f"\nTest 5 (20 < score <= 40): status={status}")
print(raw)

if status != 200:
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Numeric range filter failed")
    sys.exit(1)

# Should return 3 docs: doc2(30), doc3(40)
# Wait: doc2=30 (>20 and <=40), doc3=40 (>20 and <=40)
results = body.get("results", [[]])[0]
result_ids = [r.get("id") for r in results if isinstance(r, dict) and "id" in r]
expected_ids = ["doc2", "doc3"]
if len(result_ids) != 2:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Expected 2 results for range, got {len(result_ids)}")
    print(f"Expected: {expected_ids}, Got: {result_ids}")
    sys.exit(1)

# Cleanup
try:
    safe_request("DELETE", f"/api/v1/collections/{coll_name}")
except:
    pass

print("VERDICT: NO_DEFECT")
