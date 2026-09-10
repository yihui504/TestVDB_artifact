#!/usr/bin/env python3
"""
Attack: qdrant_type_create_collection_001 (constraints::qdrant_type_create_collection_001)
Testing: vectors.size must be positive integer - boundary and type testing
Strategy: type_validation
Endpoint: collections+create
Constraint IDs: [constraints::qdrant_type_create_collection_001]
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

# Test invalid vector sizes
invalid_sizes = [
    (0, "zero size"),
    (-1, "negative size"),
    (-100, "large negative"),
    (1.5, "float instead of int"),
    ("128", "string instead of int"),
    (None, "null value"),
    ([], "empty array"),
]

for size, description in invalid_sizes:
    collection_name = f"test_invalid_size_{abs(hash(str(size))) % 10000}_cleanup"

    # Cleanup first
    try:
        safe_request("DELETE", f"/collections/{collection_name}")
    except Exception:
        pass

    create_body = {
        "vectors": {
            "size": size,
            "distance": "Cosine"
        }
    }

    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=create_body)
    print(f"Test size={repr(size)} ({description}): status={status}, raw={raw[:200]}")

    # Should reject with error (not 200)
    if status == 200:
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — Invalid vectors.size={repr(size)} was accepted (must be positive integer)")
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

# Test valid sizes
valid_sizes = [1, 32, 128, 512, 2048, 65536]

for size in valid_sizes:
    collection_name = f"test_valid_size_{size}_cleanup"

    try:
        safe_request("DELETE", f"/collections/{collection_name}")
    except Exception:
        pass

    create_body = {
        "vectors": {
            "size": size,
            "distance": "Cosine"
        }
    }

    status, body, raw = safe_request("PUT", f"/collections/{collection_name}", json=create_body)
    print(f"Valid size={size}: status={status}")

    if status != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Valid vectors.size={size} was rejected with status {status}")
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
