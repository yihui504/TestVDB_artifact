#!/usr/bin/env python3
"""
TestVDB Attack Vein Script - null_check condition
Endpoint: PUT /collections/{collection_name}
Parameter: Null/missing value testing on required fields
Strategy: vein_null_check
"""

import os
import sys
import json
import time
import traceback
from typing import Dict, Any, Optional, Tuple

def safe_request(
    method: str,
    url: str,
    payload: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 10
) -> Tuple[Optional[int], Optional[Dict[str, Any]], Optional[str]]:
    """Safe HTTP request with timeout and error handling."""
    try:
        import urllib.request
        import urllib.error

        if headers is None:
            headers = {'Content-Type': 'application/json'}

        data = None
        if payload is not None:
            data = json.dumps(payload).encode('utf-8')

        req = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method=method
        )

        with urllib.request.urlopen(req, timeout=timeout) as response:
            status_code = response.getcode()
            response_data = response.read().decode('utf-8')
            response_json = json.loads(response_data) if response_data else None
            return status_code, response_json, None

    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else ''
        try:
            error_json = json.loads(error_body) if error_body else None
        except:
            error_json = {'error': error_body}
        return e.code, error_json, error_body
    except urllib.error.URLError as e:
        return None, None, f"Connection error: {str(e)}"
    except Exception as e:
        return None, None, f"Request error: {str(e)}"

def cleanup_collection(db_url: str, collection_name: str) -> None:
    """Clean up test collection"""
    try:
        delete_url = f"{db_url}/collections/{collection_name}"
        safe_request("DELETE", delete_url, timeout=5)
        time.sleep(0.5)
    except:
        pass

def main():
    db_url = os.environ.get("TESTVDB_DB_URL", "http://localhost:6333")
    collection_name = "vein_null_check_test_1"
    verdict = "NO_DEFECT"

    print(f"[vein_null_check_collections_put_1] Testing null_check on PUT /collections/{{collection}}")
    print(f"DB URL: {db_url}")
    print(f"Collection: {collection_name}")

    cleanup_collection(db_url, collection_name)

    findings = []

    try:
        # Test 1: Missing vectors config entirely
        print("\n[Test 1] Missing 'vectors' field (required)")
        missing_vectors_payload = {
            "hnsw_config": {
                "m": 16
            }
        }

        create_url = f"{db_url}/collections/{collection_name}"
        status, response, error = safe_request("PUT", create_url, missing_vectors_payload, timeout=10)

        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:300]}")

        if status == 200:
            print("  [DEFECT_CANDIDATE] Collection created without vectors field")
            findings.append("Missing 'vectors' field accepted - should be rejected (required field)")
            verdict = "DEFECT_FOUND"
            cleanup_collection(db_url, collection_name)
        elif status == 400 or status == 422:
            print(f"  [EXPECTED] Missing vectors rejected with {status}")
        else:
            print(f"  [UNEXPECTED] Missing vectors returned {status}")

        # Test 2: vectors field is null
        print("\n[Test 2] 'vectors' field is null")
        vectors_null_payload = {
            "vectors": None
        }

        status, response, error = safe_request("PUT", create_url, vectors_null_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:300] if response else error}")

        if status == 200:
            print("  [DEFECT_CANDIDATE] vectors=null accepted")
            findings.append("vectors=null accepted - should reject null for required field")
            verdict = "DEFECT_FOUND"
            cleanup_collection(db_url, collection_name)
        elif status == 400 or status == 422:
            print(f"  [EXPECTED] vectors=null rejected with {status}")
        else:
            print(f"  [UNEXPECTED] vectors=null returned {status}")

        # Test 3: Empty vectors object
        print("\n[Test 3] Empty vectors object {}")
        vectors_empty_payload = {
            "vectors": {}
        }

        status, response, error = safe_request("PUT", create_url, vectors_empty_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:300] if response else error}")

        if status == 200:
            print("  [DEFECT_CANDIDATE] vectors={{}} accepted")
            findings.append("vectors={} (empty) accepted - should reject (missing size/distance)")
            verdict = "DEFECT_FOUND"
            cleanup_collection(db_url, collection_name)
        elif status == 400 or status == 422:
            print(f"  [EXPECTED] vectors={{}} rejected with {status}")
        else:
            print(f"  [UNEXPECTED] vectors={{}} returned {status}")

        # Test 4: hnsw_config is null (optional field)
        print("\n[Test 4] hnsw_config is null (optional field)")
        hnsw_null_payload = {
            "vectors": {
                "size": 128,
                "distance": "Cosine"
            },
            "hnsw_config": None
        }

        status, response, error = safe_request("PUT", create_url, hnsw_null_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:300] if response else error}")

        if status == 200:
            print("  [ACCEPTED] hnsw_config=null accepted (optional field)")
            cleanup_collection(db_url, collection_name)
        elif status == 400 or status == 422:
            print(f"  [REJECTED] hnsw_config=null rejected with {status}")
        else:
            print(f"  [UNEXPECTED] hnsw_config=null returned {status}")

        # Test 5: vectors.size is null
        print("\n[Test 5] vectors.size is null")
        size_null_payload = {
            "vectors": {
                "size": None,
                "distance": "Cosine"
            }
        }

        status, response, error = safe_request("PUT", create_url, size_null_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:300] if response else error}")

        if status == 200:
            print("  [DEFECT_CANDIDATE] vectors.size=null accepted")
            findings.append("vectors.size=null accepted - should reject null for required size")
            verdict = "DEFECT_FOUND"
            cleanup_collection(db_url, collection_name)
        elif status == 400 or status == 422:
            print(f"  [EXPECTED] size=null rejected with {status}")
        else:
            print(f"  [UNEXPECTED] size=null returned {status}")

        # Test 6: vectors.distance is null
        print("\n[Test 6] vectors.distance is null")
        distance_null_payload = {
            "vectors": {
                "size": 128,
                "distance": None
            }
        }

        status, response, error = safe_request("PUT", create_url, distance_null_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:300] if response else error}")

        if status == 200:
            print("  [DEFECT_CANDIDATE] vectors.distance=null accepted")
            findings.append("vectors.distance=null accepted - should reject null for required distance")
            verdict = "DEFECT_FOUND"
            cleanup_collection(db_url, collection_name)
        elif status == 400 or status == 422:
            print(f"  [EXPECTED] distance=null rejected with {status}")
        else:
            print(f"  [UNEXPECTED] distance=null returned {status}")

        # Test 7: Both size and distance are null
        print("\n[Test 7] Both vectors.size and vectors.distance are null")
        both_null_payload = {
            "vectors": {
                "size": None,
                "distance": None
            }
        }

        status, response, error = safe_request("PUT", create_url, both_null_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:300] if response else error}")

        if status == 200:
            print("  [DEFECT_CANDIDATE] Both size and distance null accepted")
            findings.append("vectors.size=null + distance=null both accepted - should reject")
            verdict = "DEFECT_FOUND"
            cleanup_collection(db_url, collection_name)
        elif status == 400 or status == 422:
            print(f"  [EXPECTED] Both null rejected with {status}")
        else:
            print(f"  [UNEXPECTED] Both null returned {status}")

        # Test 8: optimizers_config is null (optional field)
        print("\n[Test 8] optimizers_config is null (optional field)")
        optimizers_null_payload = {
            "vectors": {
                "size": 128,
                "distance": "Cosine"
            },
            "optimizers_config": None
        }

        status, response, error = safe_request("PUT", create_url, optimizers_null_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:300] if response else error}")

        if status == 200:
            print("  [ACCEPTED] optimizers_config=null accepted (optional field)")
            cleanup_collection(db_url, collection_name)
        elif status == 400 or status == 422:
            print(f"  [REJECTED] optimizers_config=null rejected with {status}")
        else:
            print(f"  [UNEXPECTED] optimizers_config=null returned {status}")

    except Exception as e:
        print(f"\n[EXCEPTION] {str(e)}")
        traceback.print_exc()
        verdict = "SCRIPT_ERROR"

    finally:
        cleanup_collection(db_url, collection_name)

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    if findings:
        print("Findings:")
        for f in findings:
            print(f"  - {f}")
    else:
        print("No defects found")

    print("VERDICT: DEFECT_FOUND")

if __name__ == "__main__":
    main()
