#!/usr/bin/env python3
"""
TestVDB Attack Script - Type1_IllegalSuccess
vein_null_check_points_query_2.py

DEFECT: points+query accepts query=null without validation (should return 400)
STRATEGY: vein_null_check
EXPECTED: API rejects null query value with 4xx error
ACTUAL: API returns 200 OK, treating null as valid input

Reference: threat_model.json top_attack_vectors rank 2
"""

import os
import requests
import sys

DB_URL = os.environ.get('TESTVDB_DB_URL', 'http://localhost:6333')
COLLECTION_NAME = os.environ.get('TESTVDB_COLLECTION', 'test_collection')
HEADERS = {'Content-Type': 'application/json'}

def safe_request(method, path, data=None, timeout=10):
    """Safe request wrapper with error handling"""
    url = f"{DB_URL}/{path}"
    try:
        if method == 'POST':
            resp = requests.post(url, json=data, headers=HEADERS, timeout=timeout)
        elif method == 'GET':
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
        elif method == 'PUT':
            resp = requests.put(url, json=data, headers=HEADERS, timeout=timeout)
        elif method == 'DELETE':
            resp = requests.delete(url, headers=HEADERS, timeout=timeout)
        return resp.status_code, resp.json() if resp.content else None
    except Exception as e:
        return -1, str(e)

def main():
    print("Test: query=null on POST /collections/{collection}/points/query")
    print("="*80)

    # Prepare payload with null query
    payload = {
        "query": None
    }

    print(f"Request: POST /collections/{COLLECTION_NAME}/points/query")
    print(f"Payload: {payload}")

    # Send request
    status, result = safe_request('POST', f'collections/{COLLECTION_NAME}/points/query', payload)

    print(f"\nResponse Status: {status}")
    print(f"Response Body: {result}")

    # Analyze result
    print("\n" + "="*80)
    print("ANALYSIS:")
    print("="*80)

    if status == 200:
        print(f"*** DEFECT FOUND: API returned 200 OK without rejecting null query ***")
        print(f"Expected: 400 Bad Request with validation error")
        print(f"Actual: 200 OK - null value accepted")
        print(f"Result: {result}")
        VERDICT = "DEFECT_FOUND"
    elif status == 400:
        print(f"*** NO DEFECT: API properly rejected null value with 400 ***")
        VERDICT = "NO_DEFECT"
    elif status >= 500:
        print(f"*** SERVER ERROR: {status} ***")
        VERDICT = "SERVER_ERROR"
    else:
        print(f"*** INCONCLUSIVE: Status {status} ***")
        VERDICT = "INCONCLUSIVE"

    print(f"\nVERDICT: {VERDICT}")
    return 0 if VERDICT == "DEFECT_FOUND" else 1

if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(2)
    finally:
        # Cleanup: no resources to clean
        pass
