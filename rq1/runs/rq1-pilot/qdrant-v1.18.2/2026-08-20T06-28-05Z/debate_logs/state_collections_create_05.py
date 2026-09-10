#!/usr/bin/env python3
"""
Attack: state_consistency | create_boundary_values | hnsw_param_validation
Strategy: 1 (CRUD后COUNT一致性 - 边界值验证)
Endpoint: collections+create
Constraint IDs:
  - type_constraints::qdrant_type_create_collection_001
  - type_constraints::qdrant_type_create_collection_002
  - range_constraints::qdrant_range_create_collection_001
  - range_constraints::qdrant_range_create_collection_002
Source URL: https://api.qdrant.tech/api-reference/collections/create-collection
Doc Version: 1.19.x
Expected Defect Type: Type4_StateLogicViolation
Blindspot: BS-03 (Concurrency Blindness) - boundary state corruption
"""

import os
import sys
import time
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

def safe_request(method, endpoint, json=None, timeout=10):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text)
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.request(
            method=method,
            url=url,
            json=json,
            headers=headers,
            timeout=timeout
        )
        status_code = response.status_code
        raw_text = response.text

        try:
            body = response.json()
        except:
            body = raw_text

        return status_code, body, raw_text
    except Exception as e:
        return -1, str(e), str(e)

BASE_COLL = "test_state_boundary_"

# Test cases: (description, vectors_config, expected_status)
test_cases = [
    ("Valid minimal", {"size": 1, "distance": "Cosine"}, 200),
    ("Valid typical", {"size": 128, "distance": "Euclidean"}, 200),
    ("Valid large", {"size": 65536, "distance": "Manhattan"}, 200),
    ("Invalid size=0", {"size": 0, "distance": "Cosine"}, 400),
    ("Invalid size=-1", {"size": -1, "distance": "Cosine"}, 400),
    ("Invalid distance", {"size": 128, "distance": "UnknownMetric"}, 400),
]

# Test HNSW boundary values
hnsw_test_cases = [
    ("Valid HNSW m=2 (min)", {"m": 2, "ef_construct": 100}, 200),
    ("Valid HNSW m=100 (max)", {"m": 100, "ef_construct": 100}, 200),
    ("Invalid HNSW m=1 (below min)", {"m": 1, "ef_construct": 100}, 400),
    ("Invalid HNSW m=101 (above max)", {"m": 101, "ef_construct": 100}, 400),
    ("Valid HNSW ef=10 (min)", {"m": 16, "ef_construct": 10}, 200),
    ("Valid HNSW ef=1000 (max)", {"m": 16, "ef_construct": 1000}, 200),
    ("Invalid HNSW ef=9 (below min)", {"m": 16, "ef_construct": 9}, 400),
    ("Invalid HNSW ef=1001 (above max)", {"m": 16, "ef_construct": 1001}, 400),
]

def run_test(test_name, create_body, expected_status):
    """Run a single test case"""
    coll_name = f"{BASE_COLL}{test_name.replace(' ', '_').replace('(', '').replace(')', '')}"

    # Cleanup
    try:
        safe_request("DELETE", f"/collections/{coll_name}")
        time.sleep(0.05)
    except Exception:
        pass

    status, body, raw = safe_request("PUT", f"/collections/{coll_name}", json=create_body)
    print(f"[{test_name}] status={status}, expected={expected_status}")

    # Cleanup
    try:
        if status == 200:
            safe_request("DELETE", f"/collections/{coll_name}")
    except Exception:
        pass

    return status == expected_status

print("Testing vector configuration boundaries...")
results = []
for desc, vectors, expected in test_cases:
    create_body = {"vectors": vectors}
    result = run_test(desc, create_body, expected)
    results.append((desc, result))

print("\nTesting HNSW parameter boundaries...")
for desc, hnsw, expected in hnsw_test_cases:
    create_body = {
        "vectors": {"size": 128, "distance": "Cosine"},
        "hnsw_config": hnsw
    }
    result = run_test(desc, create_body, expected)
    results.append((desc, result))

# Check results
failures = [(desc, passed) for desc, passed in results if not passed]

if failures:
    print(f"\nVERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Boundary validation failures:")
    for desc, passed in failures:
        print(f"  - {desc}: expected validation failed")
    sys.exit(1)

print(f"\nVERDICT: NO_DEFECT — All boundary validations passed ({len(results)}/{len(results)})")
sys.exit(0)
