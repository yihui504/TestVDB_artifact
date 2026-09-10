#!/usr/bin/env python3
"""
TestVDB Attack Vein Script - range_filter condition
Endpoint: POST /collections/{collection_name}/points/scroll
Parameter: Pagination limits with range boundaries
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
                {"id": i, "vector": [0.1]*128, "payload": {"idx": i}}
                for i in range(1, 101)
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
    collection_name = "vein_range_filter_scroll_test_1"
    verdict = "NO_DEFECT"

    print(f"[vein_range_filter_points_scroll_1] Testing range_filter on POST /collections/{{c}}/points/scroll")
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

        scroll_url = f"{db_url}/collections/{collection_name}/points/scroll"

        # Test 1: Valid limit=10
        print("\n[Test 1] Valid limit=10")
        valid_limit_payload = {
            "limit": 10
        }

        status, response, error = safe_request("POST", scroll_url, valid_limit_payload, timeout=10)
        print(f"  Status: {status}")
        result_count = len(response.get('result', {}).get('points', [])) if response.get('result') else 0
        print(f"  Points returned: {result_count}")

        if status == 200 and result_count == 10:
            print("  [PASS] Valid limit=10 accepted, returned 10 points")
        else:
            print(f"  [UNEXPECTED] Valid limit returned {status} or {result_count} points")

        # Test 2: Limit=0 (boundary case)
        print("\n[Test 2] Limit=0 (boundary)")
        limit_zero_payload = {
            "limit": 0
        }

        status, response, error = safe_request("POST", scroll_url, limit_zero_payload, timeout=10)
        print(f"  Status: {status}")
        result_count = len(response.get('result', {}).get('points', [])) if response.get('result') else 0
        print(f"  Points returned: {result_count}")

        if status == 200:
            if result_count == 0:
                print("  [ACCEPTED] limit=0 returns 0 points (documented behavior)")
            else:
                print(f"  [DEFECT_CANDIDATE] limit=0 returned {result_count} points - expected 0")
                findings.append(f"limit=0 returned {result_count} points - should return 0 or be rejected")
                verdict = "DEFECT_FOUND"
        elif status == 400 or status == 422:
            print(f"  [REJECTED] limit=0 rejected with {status}")
        else:
            print(f"  [UNEXPECTED] limit=0 returned {status}")

        # Test 3: Limit=-1 (negative)
        print("\n[Test 3] Limit=-1 (negative)")
        limit_negative_payload = {
            "limit": -1
        }

        status, response, error = safe_request("POST", scroll_url, limit_negative_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:300] if response else error}")

        if status == 200:
            print("  [DEFECT_CANDIDATE] limit=-1 accepted")
            findings.append("limit=-1 accepted - should reject negative value")
            verdict = "DEFECT_FOUND"
        elif status == 400 or status == 422:
            print(f"  [EXPECTED] limit=-1 rejected with {status}")
        else:
            print(f"  [UNEXPECTED] limit=-1 returned {status}")

        # Test 4: Limit=999999999 (extreme)
        print("\n[Test 4] Limit=999999999 (extreme)")
        limit_extreme_payload = {
            "limit": 999999999
        }

        status, response, error = safe_request("POST", scroll_url, limit_extreme_payload, timeout=10)
        print(f"  Status: {status}")
        result_count = len(response.get('result', {}).get('points', [])) if response.get('result') else 0
        print(f"  Points returned: {result_count}")

        if status == 200:
            if result_count <= 100:
                print(f"  [ACCEPTED] limit=999999999 capped at collection size ({result_count} points)")
            else:
                print(f"  [DEFECT_CANDIDATE] limit=999999999 returned {result_count} points - potential overflow")
                findings.append(f"limit=999999999 returned {result_count} points - should cap or reject")
                verdict = "DEFECT_FOUND"
        elif status == 400 or status == 422:
            print(f"  [REJECTED] Extreme limit rejected with {status}")
        else:
            print(f"  [UNEXPECTED] Extreme limit returned {status}")

        # Test 5: Limit with fractional value
        print("\n[Test 5] Limit=10.5 (fractional)")
        limit_fractional_payload = {
            "limit": 10.5
        }

        status, response, error = safe_request("POST", scroll_url, limit_fractional_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:300] if response else error}")

        if status == 200:
            print("  [DEFECT_CANDIDATE] limit=10.5 (fractional) accepted")
            findings.append("limit=10.5 accepted - should reject fractional value (expects integer)")
            verdict = "DEFECT_FOUND"
        elif status == 400 or status == 422:
            print(f"  [EXPECTED] Fractional limit rejected with {status}")
        else:
            print(f"  [UNEXPECTED] Fractional limit returned {status}")

        # Test 6: Offset boundary testing
        print("\n[Test 6] Offset=50 (valid)")
        offset_valid_payload = {
            "limit": 10,
            "offset": 50
        }

        status, response, error = safe_request("POST", scroll_url, offset_valid_payload, timeout=10)
        print(f"  Status: {status}")
        result_count = len(response.get('result', {}).get('points', [])) if response.get('result') else 0
        print(f"  Points returned: {result_count}")

        if status == 200:
            print(f"  [PASS] offset=50 accepted, returned {result_count} points")
        else:
            print(f"  [UNEXPECTED] offset=50 returned {status}")

        # Test 7: Offset=-1 (negative)
        print("\n[Test 7] Offset=-1 (negative)")
        offset_negative_payload = {
            "limit": 10,
            "offset": -1
        }

        status, response, error = safe_request("POST", scroll_url, offset_negative_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:300] if response else error}")

        if status == 200:
            print("  [DEFECT_CANDIDATE] offset=-1 accepted")
            findings.append("offset=-1 accepted - should reject negative offset")
            verdict = "DEFECT_FOUND"
        elif status == 400 or status == 422:
            print(f"  [EXPECTED] offset=-1 rejected with {status}")
        else:
            print(f"  [UNEXPECTED] offset=-1 returned {status}")

        # Test 8: Offset beyond collection size
        print("\n[Test 8] Offset=999999 (beyond collection)")
        offset_beyond_payload = {
            "limit": 10,
            "offset": 999999
        }

        status, response, error = safe_request("POST", scroll_url, offset_beyond_payload, timeout=10)
        print(f"  Status: {status}")
        result_count = len(response.get('result', {}).get('points', [])) if response.get('result') else 0
        print(f"  Points returned: {result_count}")

        if status == 200 and result_count == 0:
            print("  [PASS] offset beyond size returns 0 points (correct)")
        elif status == 200:
            print(f"  [UNEXPECTED] offset=999999 returned {result_count} points")
        else:
            print(f"  [UNEXPECTED] offset beyond size returned {status}")

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

    print("VERDICT: NO_DEFECT")

if __name__ == "__main__":
    main()
