#!/usr/bin/env python3
"""
Attack: qdrant_range_create_collection_001 (constraints::qdrant_range_create_collection_001)
Testing: hnsw_config.m (max connections) in range [2, 100] - boundary testing
Strategy: boundary_testing
Endpoint: collections+create
Constraint IDs: [constraints::qdrant_range_create_collection_001]
Source URL: https://api.qdrant.tech/api-reference/collections/create-collection
Doc Version: 1.19.x
Expected Defect Type: Type1_IllegalSuccess
"""

import os
import sys

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

def safe_request(method, endpoint, json=None, timeout=10):
    """Safe HTTP request wrapper with unified error handling."""
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}

    try:
        import requests
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

# Test values outside [2, 100] range
test_cases = [
    (0, "below minimum"),
    (1, "one below minimum"),
    (101, "one above maximum"),
    (200, "far above maximum"),
    (-5, "negative value"),
]

for m_value, description in test_cases:
    collection_name = f"test_range_m_{m_value}_cleanup"

    # Cleanup first
    try:
        safe_request("DELETE", f"/collections/{collection_name}")
    except Exception:
        pass

    create_body = {
        "vectors": {
            "size": 32,
            "distance": "Dot"
        },
        "hnsw_config": {
            "m": m_value
        }
    }

    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=create_body)
    print(f"Test m={m_value} ({description}): status={status}, raw={raw[:200]}")

    # Should reject with error (not 200)
    if status == 200:
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — Invalid hnsw_config.m={m_value} was accepted (range is [2, 100])")
        # Cleanup
        try:
            safe_request("DELETE", f"/collections/{collection_name}")
        except Exception:
            pass
        sys.exit(1)

    # Cleanup
    try:
        safe_request("DELETE", f"/collections/{collection_name}")
    except Exception:
        pass

# Test valid boundaries
valid_cases = [2, 50, 100]

for m_value in valid_cases:
    collection_name = f"test_valid_m_{m_value}_cleanup"

    try:
        safe_request("DELETE", f"/collections/{collection_name}")
    except Exception:
        pass

    create_body = {
        "vectors": {
            "size": 32,
            "distance": "Dot"
        },
        "hnsw_config": {
            "m": m_value
        }
    }

    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=create_body)
    print(f"Valid m={m_value}: status={status}")

    if status != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Valid hnsw_config.m={m_value} was rejected with status {status}")
        try:
            safe_request("DELETE", f"/collections/{collection_name}")
        except Exception:
            pass
        sys.exit(1)

    # Cleanup
    try:
        safe_request("DELETE", f"/collections/{collection_name}")
    except Exception:
        pass

print("VERDICT: NO_DEFECT")
sys.exit(0)
