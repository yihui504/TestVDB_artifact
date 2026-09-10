#!/usr/bin/env python3
"""
TestVDB Attack Vein Script - range_filter condition
Endpoint: POST /collections/{collection_name}/points/delete
Parameter: Filter conditions with range boundaries
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

def setup_test_collection(db_url: str, collection_name: str) -> bool:
    """Create test collection and insert points"""
    try:
        # Create collection
        create_url = f"{db_url}/collections/{collection_name}"
        create_payload = {
            "vectors": {
                "size": 128,
                "distance": "Cosine"
            }
        }
        status, response, _ = safe_request("PUT", create_url, create_payload, timeout=10)
        if status != 200:
            return False

        time.sleep(0.5)

        # Insert test points
        points_url = f"{db_url}/collections/{collection_name}/points"
        points_payload = {
            "points": [
                {"id": 1, "vector": [0.1]*128, "payload": {"category": "A", "score": 10}},
                {"id": 2, "vector": [0.2]*128, "payload": {"category": "B", "score": 20}},
                {"id": 3, "vector": [0.3]*128, "payload": {"category": "A", "score": 30}},
                {"id": 4, "vector": [0.4]*128, "payload": {"category": "B", "score": 40}},
                {"id": 5, "vector": [0.5]*128, "payload": {"category": "A", "score": 50}}
            ]
        }
        status, response, _ = safe_request("PUT", points_url, points_payload, timeout=10)
        if status != 200:
            return False

        time.sleep(0.5)
        return True

    except Exception as e:
        print(f"Setup error: {e}")
        return False

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
    collection_name = "vein_range_filter_delete_test_1"
    verdict = "NO_DEFECT"

    print(f"[vein_range_filter_points_delete_1] Testing range_filter on POST /collections/{{c}}/points/delete")
    print(f"DB URL: {db_url}")
    print(f"Collection: {collection_name}")

    cleanup_collection(db_url, collection_name)

    findings = []

    try:
        # Setup test collection
        if not setup_test_collection(db_url, collection_name):
            print("Failed to setup test collection")
            verdict = "SCRIPT_ERROR"
            return

        delete_url = f"{db_url}/collections/{collection_name}/points/delete"

        # Test 1: Valid range filter (score >= 30)
        print("\n[Test 1] Valid range filter - score >= 30")
        valid_range_payload = {
            "filter": {
                "must": [
                    {
                        "key": "score",
                        "range": {
                            "gte": 30
                        }
                    }
                ]
            }
        }

        status, response, error = safe_request("POST", delete_url, valid_range_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:300]}")

        if status == 200:
            print("  [PASS] Valid range filter accepted")
        else:
            print(f"  [UNEXPECTED] Valid filter rejected with {status}")

        # Test 2: Range with negative bounds (score <= -100)
        print("\n[Test 2] Range with negative bounds - score <= -100")
        negative_range_payload = {
            "filter": {
                "must": [
                    {
                        "key": "score",
                        "range": {
                            "lte": -100
                        }
                    }
                ]
            }
        }

        status, response, error = safe_request("POST", delete_url, negative_range_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:300] if response else error}")

        if status == 200:
            print("  [ACCEPTED] Negative range bounds accepted (may match zero points)")
        elif status == 400 or status == 422:
            print(f"  [REJECTED] Negative range rejected with {status}")
        else:
            print(f"  [UNEXPECTED] Negative range returned {status}")

        # Test 3: Range with extreme values (score >= 999999999)
        print("\n[Test 3] Range with extreme values - score >= 999999999")
        extreme_range_payload = {
            "filter": {
                "must": [
                    {
                        "key": "score",
                        "range": {
                            "gte": 999999999
                        }
                    }
                ]
            }
        }

        status, response, error = safe_request("POST", delete_url, extreme_range_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:300] if response else error}")

        if status == 200:
            print("  [ACCEPTED] Extreme range accepted (may match zero points)")
        elif status == 400 or status == 422:
            print(f"  [REJECTED] Extreme range rejected with {status}")
        else:
            print(f"  [UNEXPECTED] Extreme range returned {status}")

        # Test 4: Range with gte > lte (invalid bounds)
        print("\n[Test 4] Range with gte > lte (invalid bounds) - gte=100, lte=50")
        invalid_bounds_payload = {
            "filter": {
                "must": [
                    {
                        "key": "score",
                        "range": {
                            "gte": 100,
                            "lte": 50
                        }
                    }
                ]
            }
        }

        status, response, error = safe_request("POST", delete_url, invalid_bounds_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:300] if response else error}")

        if status == 200:
            print("  [DEFECT_CANDIDATE] Invalid bounds (gte > lte) accepted without error")
            findings.append("Range with gte=100, lte=50 accepted - should validate that gte <= lte")
            verdict = "DEFECT_FOUND"
        elif status == 400 or status == 422:
            print(f"  [EXPECTED] Invalid bounds rejected with {status}")
        else:
            print(f"  [UNEXPECTED] Invalid bounds returned {status}")

        # Test 5: Range with fractional bounds (score >= 20.5)
        print("\n[Test 5] Range with fractional bounds - score >= 20.5")
        fractional_range_payload = {
            "filter": {
                "must": [
                    {
                        "key": "score",
                        "range": {
                            "gte": 20.5
                        }
                    }
                ]
            }
        }

        status, response, error = safe_request("POST", delete_url, fractional_range_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:300] if response else error}")

        if status == 200:
            print("  [ACCEPTED] Fractional bounds accepted")
        elif status == 400 or status == 422:
            print(f"  [REJECTED] Fractional bounds rejected with {status}")
        else:
            print(f"  [UNEXPECTED] Fractional bounds returned {status}")

        # Test 6: Filter is null (should delete all points?)
        print("\n[Test 6] Filter is null")
        filter_null_payload = {
            "filter": None
        }

        status, response, error = safe_request("POST", delete_url, filter_null_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:300] if response else error}")

        if status == 200:
            print("  [DEFECT_CANDIDATE] filter=null accepted - undefined behavior")
            findings.append("filter=null accepted - should specify behavior (delete all? error?)")
            verdict = "DEFECT_FOUND"
        elif status == 400 or status == 422:
            print(f"  [EXPECTED] filter=null rejected with {status}")
        else:
            print(f"  [UNEXPECTED] filter=null returned {status}")

        # Test 7: Empty filter object
        print("\n[Test 7] Empty filter object {}")
        empty_filter_payload = {
            "filter": {}
        }

        status, response, error = safe_request("POST", delete_url, empty_filter_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:300] if response else error}")

        if status == 200:
            print("  [DEFECT_CANDIDATE] Empty filter {{}} accepted - unclear semantics")
            findings.append("Empty filter {} accepted - should specify behavior (no-op? delete all?)")
            verdict = "DEFECT_FOUND"
        elif status == 400 or status == 422:
            print(f"  [EXPECTED] Empty filter rejected with {status}")
        else:
            print(f"  [UNEXPECTED] Empty filter returned {status}")

        # Test 8: Range with both gte and gt (redundant bounds)
        print("\n[Test 8] Range with both gte and gt - gte=20, gt=30")
        redundant_bounds_payload = {
            "filter": {
                "must": [
                    {
                        "key": "score",
                        "range": {
                            "gte": 20,
                            "gt": 30
                        }
                    }
                ]
            }
        }

        status, response, error = safe_request("POST", delete_url, redundant_bounds_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:300] if response else error}")

        if status == 200:
            print("  [ACCEPTED] Redundant bounds accepted (uses more restrictive)")
        elif status == 400 or status == 422:
            print(f"  [REJECTED] Redundant bounds rejected with {status}")
        else:
            print(f"  [UNEXPECTED] Redundant bounds returned {status}")

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
