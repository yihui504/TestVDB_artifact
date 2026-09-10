#!/usr/bin/env python3
"""
Attack: count_consistency
Test: Empty collection search — verify returns empty array (no error)
Endpoint: points+search
Constraint: qdrant_behavioral_search_points_002
Source: https://api.qdrant.tech/api-reference/points/search-points
Doc Version: 1.19.x
"""

import os
import sys
import time
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

COLL = "state_search_04"
VECTOR_DIM = 128

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

def setup_collection():
    """Create test collection"""
    create_body = {
        "vectors": {
            "size": VECTOR_DIM,
            "distance": "Cosine"
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{COLL}", json=create_body)
    print(f"Create collection: status={status}")
    return status == 200

def search_empty():
    """Search empty collection"""
    query_vector = [0.1] * VECTOR_DIM
    search_body = {
        "vector": query_vector,
        "limit": 1000,
        "with_payload": True
    }

    status, body, raw = safe_request("POST", f"/collections/{COLL}/points/search", json=search_body)
    print(f"Search empty collection: status={status}, raw={raw[:200]}")
    return status, body

def main():
    # Cleanup existing
    try:
        safe_request("DELETE", f"/collections/{COLL}")
    except:
        pass

    if not setup_collection():
        print("VERDICT: SCRIPT_ERROR — Failed to create collection")
        sys.exit(2)

    time.sleep(0.5)

    status, body = search_empty()

    # Test 1: Status must be 200 OK
    if status != 200:
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Empty search returned status {status}, expected 200")
        try:
            safe_request("DELETE", f"/collections/{COLL}")
        except:
            pass
        sys.exit(1)

    # Test 2: Result must be empty array
    try:
        result = body.get("result")
        if result is None:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Response missing 'result' field: {body}")
            try:
                safe_request("DELETE", f"/collections/{COLL}")
            except:
                pass
            sys.exit(1)

        if not isinstance(result, list):
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — 'result' is not a list: {type(result)}")
            try:
                safe_request("DELETE", f"/collections/{COLL}")
            except:
                pass
            sys.exit(1)

        if len(result) != 0:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Empty collection returned {len(result)} results")
            try:
                safe_request("DELETE", f"/collections/{COLL}")
            except:
                pass
            sys.exit(1)

    except Exception as e:
        print(f"VERDICT: SCRIPT_ERROR — Failed to parse response: {e}")
        try:
            safe_request("DELETE", f"/collections/{COLL}")
        except:
            pass
        sys.exit(2)

    print("VERDICT: NO_DEFECT")

    # Cleanup
    try:
        safe_request("DELETE", f"/collections/{COLL}")
    except Exception:
        pass

if __name__ == "__main__":
    main()
