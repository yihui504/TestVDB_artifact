#!/usr/bin/env python3
"""
Attack: behavioral_contract (qdrant_behavioral_search_points_001)
Verifies search returns 200 OK with scored results sorted by similarity.
"""
import os
import sys
import requests
import time

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

# Setup
COLLECTION_NAME = "test_search_behavioral"
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

# Insert test points with varying similarity
UPSERT_PATH = f"/collections/{COLLECTION_NAME}/points"
test_points = [
    {"id": 1, "vector": [0.0] * 128},
    {"id": 2, "vector": [0.01] * 128},
    {"id": 3, "vector": [0.1] * 128},
    {"id": 4, "vector": [1.0] * 128},
]

for point in test_points:
    status, _, raw = safe_request("PUT", UPSERT_PATH, json={"points": [point]})
    if status not in (200, 201, 204):
        print(f"VERDICT: SCRIPT_ERROR — insert failed for point {point['id']}: {status}")
        sys.exit(2)

time.sleep(0.5)  # Allow index to settle

# Test: search with query vector
SEARCH_PATH = f"/collections/{COLLECTION_NAME}/points/search"
query_vector = [0.0] * 128

status, body, raw = safe_request("POST", SEARCH_PATH, json={"vector": query_vector, "limit": 10})
print(raw)

if status != 200:
    print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — search should return 200 OK but got status={status}")
    sys.exit(1)

# Extract results from qdrant response
results = body.get("result") if isinstance(body, dict) else None
if results is None or not isinstance(results, list):
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — response should contain 'result' array")
    sys.exit(1)

if len(results) == 0:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — search should return inserted points")
    sys.exit(1)

# Verify results are scored (each result should have 'score')
for i, result in enumerate(results):
    if not isinstance(result, dict) or "score" not in result:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — result {i} should have 'score' field")
        sys.exit(1)

# Verify results are sorted by similarity (scores should be descending or ascending based on distance)
scores = [r.get("score") for r in results]
if scores != sorted(scores, reverse=True):
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — results should be sorted by similarity score")
    print(f"Got scores: {scores}")
    sys.exit(1)

# Verify closest point (id=1 with all zeros) is first
first_id = results[0].get("id")
if first_id != 1:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — closest point (id=1) should be first, got id={first_id}")
    sys.exit(1)

print(f"VERDICT: NO_DEFECT — search returns scored results sorted by similarity")
