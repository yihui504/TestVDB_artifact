#!/usr/bin/env python3
"""
Attack: qdrant_type_create_collection_002 (constraints::qdrant_type_create_collection_002)
Testing: vectors.distance must be one of: Cosine, Euclidean, Dot, Manhattan
Strategy: type_validation
Endpoint: collections+create
Constraint IDs: [constraints::qdrant_type_create_collection_002]
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

# Test invalid distance values
invalid_distances = [
    "cosine",  # wrong case
    "EUCLIDEAN",  # wrong case
    "Jaccard",  # not supported
    "Hamming",  # not supported
    "InvalidMetric",  # nonexistent
    "",  # empty string
    123,  # integer instead of string
]

for distance in invalid_distances:
    collection_name = f"test_invalid_dist_{distance}_{abs(hash(str(distance))) % 10000}_cleanup"

    # Cleanup first
    try:
        safe_request("DELETE", f"/collections/{collection_name}")
    except Exception:
        pass

    create_body = {
        "vectors": {
            "size": 32,
            "distance": distance
        }
    }

    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=create_body)
    print(f"Test distance={repr(distance)}: status={status}, raw={raw[:200]}")

    # Should reject with error (not 200)
    if status == 200:
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — Invalid distance={repr(distance)} was accepted (must be Cosine/Euclidean/Dot/Manhattan)")
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

# Test valid distances
valid_distances = ["Cosine", "Euclidean", "Dot", "Manhattan"]

for distance in valid_distances:
    collection_name = f"test_valid_dist_{distance}_cleanup"

    try:
        safe_request("DELETE", f"/collections/{collection_name}")
    except Exception:
        pass

    create_body = {
        "vectors": {
            "size": 32,
            "distance": distance
        }
    }

    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=create_body)
    print(f"Valid distance={distance}: status={status}")

    if status != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Valid distance={distance} was rejected with status {status}")
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
