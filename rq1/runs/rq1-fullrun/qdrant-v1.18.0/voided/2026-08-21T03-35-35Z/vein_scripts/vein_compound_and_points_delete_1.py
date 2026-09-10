#!/usr/bin/env python3
"""
TestVDB Attack Vein Script - compound_and condition
Endpoint: POST /collections/{collection_name}/points/delete
Parameter: Multiple filter conditions combined with AND
Strategy: vein_compound_and
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
                {"id": 1, "vector": [0.1]*128, "payload": {"category": "A", "score": 10, "tag": "x"}},
                {"id": 2, "vector": [0.2]*128, "payload": {"category": "B", "score": 20, "tag": "y"}},
                {"id": 3, "vector": [0.3]*128, "payload": {"category": "A", "score": 30, "tag": "z"}},
                {"id": 4, "vector": [0.4]*128, "payload": {"category": "B", "score": 40, "tag": "x"}},
                {"id": 5, "vector": [0.5]*128, "payload": {"category": "A", "score": 50, "tag": "y"}}
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
    collection_name = "vein_compound_and_delete_test_1"
    verdict = "NO_DEFECT"

    print(f"[vein_compound_and_points_delete_1] Testing compound_and on POST /collections/{{c}}/points/delete")
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

        # Test 1: Valid compound - two range filters with AND
        print("\n[Test 1] Valid compound - score >= 30 AND category = A")
        valid_compound_payload = {
            "filter": {
                "must": [
                    {"key": "score", "range": {"gte": 30}},
                    {"key": "category", "match": {"value": "A"}}
                ]
            }
        }

        status, response, error = safe_request("POST", delete_url, valid_compound_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:300]}")

        if status == 200:
            print("  [PASS] Valid compound filter accepted")
        else:
            print(f"  [UNEXPECTED] Valid compound rejected with {status}")

        # Test 2: Compound with one invalid range (gte > lte)
        print("\n[Test 2] Compound with invalid range - score >= 100 AND score <= 50")
        compound_invalid_range_payload = {
            "filter": {
                "must": [
                    {"key": "score", "range": {"gte": 100, "lte": 50}}
                ]
            }
        }

        status, response, error = safe_request("POST", delete_url, compound_invalid_range_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:300] if response else error}")

        if status == 200:
            print("  [DEFECT_CANDIDATE] Compound with invalid range (gte > lte) accepted")
            findings.append("Compound filter with gte=100, lte=50 accepted - should validate bounds")
            verdict = "DEFECT_FOUND"
        elif status == 400 or status == 422:
            print(f"  [EXPECTED] Invalid range rejected with {status}")
        else:
            print(f"  [UNEXPECTED] Invalid range returned {status}")

        # Test 3: Compound with three conditions (must + must + must_not)
        print("\n[Test 3] Compound with three conditions - must AND must AND must_not")
        compound_triple_payload = {
            "filter": {
                "must": [
                    {"key": "score", "range": {"gte": 20}},
                    {"key": "category", "match": {"value": "A"}}
                ],
                "must_not": [
                    {"key": "tag", "match": {"value": "x"}}
                ]
            }
        }

        status, response, error = safe_request("POST", delete_url, compound_triple_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:300] if response else error}")

        if status == 200:
            print("  [PASS] Triple compound filter accepted")
        elif status == 400 or status == 422:
            print(f"  [REJECTED] Triple compound rejected with {status}")
        else:
            print(f"  [UNEXPECTED] Triple compound returned {status}")

        # Test 4: Compound with nested invalid bounds
        print("\n[Test 4] Compound - valid condition AND invalid range")
        compound_mixed_payload = {
            "filter": {
                "must": [
                    {"key": "category", "match": {"value": "A"}},
                    {"key": "score", "range": {"gte": 999999, "lte": 0}}
                ]
            }
        }

        status, response, error = safe_request("POST", delete_url, compound_mixed_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:300] if response else error}")

        if status == 200:
            print("  [DEFECT_CANDIDATE] Compound with mixed valid/invalid conditions accepted")
            findings.append("Compound with valid category + invalid score range accepted - should validate")
            verdict = "DEFECT_FOUND"
        elif status == 400 or status == 422:
            print(f"  [EXPECTED] Mixed conditions rejected with {status}")
        else:
            print(f"  [UNEXPECTED] Mixed conditions returned {status}")

        # Test 5: Compound with is_null condition
        print("\n[Test 5] Compound - is_null AND range")
        compound_isnull_payload = {
            "filter": {
                "must": [
                    {"key": "nonexistent_field", "is_null": True},
                    {"key": "score", "range": {"gte": 30}}
                ]
            }
        }

        status, response, error = safe_request("POST", delete_url, compound_isnull_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:300] if response else error}")

        if status == 200:
            print("  [ACCEPTED] is_null compound accepted")
        elif status == 400 or status == 422:
            print(f"  [REJECTED] is_null compound rejected with {status}")
        else:
            print(f"  [UNEXPECTED] is_null compound returned {status}")

        # Test 6: Compound with empty must array
        print("\n[Test 6] Compound - empty must array")
        compound_empty_must_payload = {
            "filter": {
                "must": [],
                "must_not": [
                    {"key": "category", "match": {"value": "A"}}
                ]
            }
        }

        status, response, error = safe_request("POST", delete_url, compound_empty_must_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:300] if response else error}")

        if status == 200:
            print("  [DEFECT_CANDIDATE] Empty must array with must_not accepted")
            findings.append("Compound with empty must[] + must_not accepted - unclear semantics")
            verdict = "DEFECT_FOUND"
        elif status == 400 or status == 422:
            print(f"  [EXPECTED] Empty must rejected with {status}")
        else:
            print(f"  [UNEXPECTED] Empty must returned {status}")

        # Test 7: Compound with contradictory conditions (always false)
        print("\n[Test 7] Compound - contradictory conditions (score >= 100 AND score <= 50)")
        compound_contradictory_payload = {
            "filter": {
                "must": [
                    {"key": "score", "range": {"gte": 100}},
                    {"key": "score", "range": {"lte": 50}}
                ]
            }
        }

        status, response, error = safe_request("POST", delete_url, compound_contradictory_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:300] if response else error}")

        if status == 200:
            print("  [DEFECT_CANDIDATE] Contradictory compound accepted (always false)")
            findings.append("Contradictory compound (score>=100 AND score<=50) accepted - should validate")
            verdict = "DEFECT_FOUND"
        elif status == 400 or status == 422:
            print(f"  [EXPECTED] Contradictory conditions rejected with {status}")
        else:
            print(f"  [UNEXPECTED] Contradictory conditions returned {status}")

        # Test 8: Nested compound (compound within compound)
        print("\n[Test 8] Nested compound - compound inside must")
        nested_compound_payload = {
            "filter": {
                "must": [
                    {
                        "must": [
                            {"key": "score", "range": {"gte": 30}},
                            {"key": "category", "match": {"value": "A"}}
                        ]
                    }
                ]
            }
        }

        status, response, error = safe_request("POST", delete_url, nested_compound_payload, timeout=10)
        print(f"  Status: {status}")
        print(f"  Response: {json.dumps(response, indent=2)[:300] if response else error}")

        if status == 200:
            print("  [PASS] Nested compound accepted")
        elif status == 400 or status == 422:
            print(f"  [REJECTED] Nested compound rejected with {status}")
        else:
            print(f"  [UNEXPECTED] Nested compound returned {status}")

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
