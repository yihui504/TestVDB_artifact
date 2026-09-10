#!/usr/bin/env python3
"""
Attack: type_confusion (qdrant_range_search_points_001 score_threshold type coercion)
Tests implicit type conversion for score_threshold parameter (expects number).
"""
import os
import sys
import requests

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
COLLECTION_NAME = "test_search_score_type"
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

# Test: type confusion variants for score_threshold
SEARCH_PATH = f"/collections/{COLLECTION_NAME}/points/search"
test_vector = [0.1] * 128

test_cases = [
    ("string '0.5'", {"vector": test_vector, "limit": 10, "score_threshold": "0.5"}),
    ("integer 1", {"vector": test_vector, "limit": 10, "score_threshold": 1}),
    ("boolean false", {"vector": test_vector, "limit": 10, "score_threshold": False}),
]

for desc, payload in test_cases:
    status, _, raw = safe_request("POST", SEARCH_PATH, json=payload)
    print(f"Test: {desc} -> status={status}")

    if status == 200:
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — {desc} should be rejected as non-numeric score_threshold")
        sys.exit(1)

print("VERDICT: NO_DEFECT — all score_threshold type confusion variants properly rejected")
