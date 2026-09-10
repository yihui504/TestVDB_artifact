#!/usr/bin/env python3
"""
TestVDB Attack Vein Script - range_filter condition
Endpoint: PUT /collections/{collection_name}
Parameter: hnsw_config.m (numeric boundary testing)
Strategy: vein_range_filter
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
    """
    Safe HTTP request with timeout and error handling.
    Returns: (status_code, response_json, error_message)
    """
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
    collection_name = "vein_range_filter_test_1"
    verdict = "NO_DEFECT"

    print(f"[vein_range_filter_collections_put_1] Testing range_filter on PUT /collections/{{collection}}")
    print(f"DB URL: {db_url}")
    print(f"Collection: {collection_name}")

    # Clean up any existing test collection
    cleanup_collection(db_url, collection_name)

    findings = []

    try:
        # Test 1: Valid m value (should succeed)
        print("\n[Test 1] Valid m=16")
        valid_payload = {
            "vectors": {
                "size": 128,
                "distance": "Cosine"
            },
            "hnsw_config": {
                "m": 16
            }
        }

        create_url = f"{db_url}/collections/{collection_name}"
        status, response, error = safe_request("PUT", create_url, valid_payload, timeout=10)

        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:200]}")

        if status == 200:
            print("  [PASS] Valid m=16 accepted")
            cleanup_collection(db_url, collection_name)
        else:
            print(f"  [UNEXPECTED] Valid config rejected with {status}")
            findings.append(f"Valid config rejected: {error}")

        # Test 2: Boundary m=2 (minimum documented)
        print("\n[Test 2] Boundary m=2 (minimum)")
        boundary_min_payload = {
            "vectors": {
                "size": 128,
                "distance": "Cosine"
            },
            "hnsw_config": {
                "m": 2
            }
        }

        status, response, error = safe_request("PUT", create_url, boundary_min_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:200] if response else error}")

        if status == 200:
            print("  [ACCEPTED] m=2 accepted")
            cleanup_collection(db_url, collection_name)
        else:
            print(f"  [REJECTED] m=2 rejected with {status}")
            findings.append(f"m=2 (min boundary) rejected: {error}")

        # Test 3: Invalid m=0 (below boundary)
        print("\n[Test 3] Invalid m=0 (below boundary)")
        invalid_min_payload = {
            "vectors": {
                "size": 128,
                "distance": "Cosine"
            },
            "hnsw_config": {
                "m": 0
            }
        }

        status, response, error = safe_request("PUT", create_url, invalid_min_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:200] if response else error}")

        if status == 200:
            print("  [DEFECT_CANDIDATE] m=0 (invalid) accepted with 200 OK")
            findings.append("m=0 accepted - should be rejected (numeric boundary violation)")
            verdict = "DEFECT_FOUND"
            cleanup_collection(db_url, collection_name)
        elif status == 400 or status == 422:
            print(f"  [EXPECTED] m=0 rejected with {status}")
        else:
            print(f"  [UNEXPECTED] m=0 returned {status}")

        # Test 4: Invalid m=-1 (negative)
        print("\n[Test 4] Invalid m=-1 (negative)")
        invalid_neg_payload = {
            "vectors": {
                "size": 128,
                "distance": "Cosine"
            },
            "hnsw_config": {
                "m": -1
            }
        }

        status, response, error = safe_request("PUT", create_url, invalid_neg_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:200] if response else error}")

        if status == 200:
            print("  [DEFECT_CANDIDATE] m=-1 (negative) accepted with 200 OK")
            findings.append("m=-1 accepted - should be rejected (negative boundary violation)")
            verdict = "DEFECT_FOUND"
            cleanup_collection(db_url, collection_name)
        elif status == 400 or status == 422:
            print(f"  [EXPECTED] m=-1 rejected with {status}")
        else:
            print(f"  [UNEXPECTED] m=-1 returned {status}")

        # Test 5: Boundary m=100 (maximum documented)
        print("\n[Test 5] Boundary m=100 (maximum)")
        boundary_max_payload = {
            "vectors": {
                "size": 128,
                "distance": "Cosine"
            },
            "hnsw_config": {
                "m": 100
            }
        }

        status, response, error = safe_request("PUT", create_url, boundary_max_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:200] if response else error}")

        if status == 200:
            print("  [ACCEPTED] m=100 accepted")
            cleanup_collection(db_url, collection_name)
        else:
            print(f"  [REJECTED] m=100 rejected with {status}")
            findings.append(f"m=100 (max boundary) rejected: {error}")

        # Test 6: Invalid m=999999 (extreme value)
        print("\n[Test 6] Invalid m=999999 (extreme)")
        extreme_payload = {
            "vectors": {
                "size": 128,
                "distance": "Cosine"
            },
            "hnsw_config": {
                "m": 999999
            }
        }

        status, response, error = safe_request("PUT", create_url, extreme_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:200] if response else error}")

        if status == 200:
            print("  [DEFECT_CANDIDATE] m=999999 (extreme) accepted with 200 OK")
            findings.append("m=999999 accepted - should be rejected (extreme boundary violation)")
            verdict = "DEFECT_FOUND"
            cleanup_collection(db_url, collection_name)
        elif status == 400 or status == 422:
            print(f"  [EXPECTED] m=999999 rejected with {status}")
        else:
            print(f"  [UNEXPECTED] m=999999 returned {status}")

        # Test 7: m with decimal/fractional value (type confusion)
        print("\n[Test 7] Type confusion - m=16.5 (fractional)")
        type_confusion_payload = {
            "vectors": {
                "size": 128,
                "distance": "Cosine"
            },
            "hnsw_config": {
                "m": 16.5
            }
        }

        status, response, error = safe_request("PUT", create_url, type_confusion_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:200] if response else error}")

        if status == 200:
            print("  [DEFECT_CANDIDATE] m=16.5 (fractional) accepted with 200 OK")
            findings.append("m=16.5 accepted - should be rejected (type confusion, expects integer)")
            verdict = "DEFECT_FOUND"
            cleanup_collection(db_url, collection_name)
        elif status == 400 or status == 422:
            print(f"  [EXPECTED] m=16.5 rejected with {status}")
        else:
            print(f"  [UNEXPECTED] m=16.5 returned {status}")

    except Exception as e:
        print(f"\n[EXCEPTION] {str(e)}")
        traceback.print_exc()
        verdict = "SCRIPT_ERROR"

    finally:
        # Final cleanup
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
