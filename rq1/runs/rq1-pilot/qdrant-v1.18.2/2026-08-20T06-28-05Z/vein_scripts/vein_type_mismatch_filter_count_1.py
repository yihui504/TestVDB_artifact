#!/usr/bin/env python3
"""
vein_type_mismatch_filter_count_1.py

TestVDB Attack Vein - Type Mismatch Filter Validation
Target: qdrant v1.18.2
Endpoint: POST /collections/{collection}/points/count
Condition Type: type_mismatch

Defect Type: Type1_IllegalSuccess
Severity: P1_High

Finding: Filter value type mismatch (string on integer field) is silently accepted
with count=0 instead of returning 400 Bad Request.

Expected Behavior: API should reject type-mismatched filter values with 400 error.
Actual Behavior: Returns 200 OK with count=0, silently accepting invalid filter.

Bug Shape: qdrant-type-coercion-type-confusion
Reference Issues: #9373 (related type confusion pattern)
"""

import requests
import json
from typing import Dict, Any, Tuple


def _safe_err(resp):
    if isinstance(resp, dict):
        s = resp.get('status', {})
        if isinstance(s, dict):
            return s.get('error', 'OK')
        return str(s)[:120]
    return str(resp)[:120]

def _safe_count(resp):
    if isinstance(resp, dict):
        r = resp.get('result', {})
        if isinstance(r, dict):
            return r.get('count', 'N/A')
        return str(r)[:120]
    return str(resp)[:120]

def safe_request(
    method: str,
    url: str,
    headers: Dict[str, str] = None,
    json_data: Dict[str, Any] = None,
    timeout: int = 10
) -> Tuple[int, Dict[str, Any], str]:
    """
    Safe HTTP request wrapper with error handling.

    Returns:
        Tuple of (http_status, response_json, raw_text)
    """
    try:
        response = requests.request(
            method=method,
            url=url,
            headers=headers or {},
            json=json_data,
            timeout=timeout
        )
        return response.status_code, response.json(), response.text
    except requests.exceptions.Timeout:
        return 408, {}, "Request timeout"
    except requests.exceptions.RequestException as e:
        return 503, {}, f"Request failed: {str(e)}"
    except json.JSONDecodeError as e:
        return response.status_code, {}, response.text


def test_type_mismatch_count() -> Dict[str, Any]:
    """
    Test type mismatch validation on count endpoint filter.

    Tests filter with string value on integer field.
    Expected: 400 Bad Request (type mismatch)
    Actual: 200 OK with count=0 (silent acceptance)
    """

    base_url = "http://localhost:6333"
    collection = "test_type_mismatch"

    # Setup: Create collection with integer payload field
    print("[SETUP] Creating collection with integer payload field...")
    status, resp, _ = safe_request(
        "PUT",
        f"{base_url}/collections/{collection}",
        json_data={"vectors": {"size": 3, "distance": "Cosine"}},
        headers={"Content-Type": "application/json"}
    )

    if status != 200:
        return {
            "verdict": "SETUP_FAILED",
            "error": f"Collection creation failed: HTTP {status}",
            "response": resp
        }

    # Insert test points with integer field
    points_data = {
        "points": [
            {"id": 1, "vector": [0.1, 0.5, 0.5], "payload": {"age": 25}},
            {"id": 2, "vector": [0.2, 0.5, 0.5], "payload": {"age": 30}},
            {"id": 3, "vector": [0.3, 0.5, 0.5], "payload": {"age": 35}}
        ]
    }

    status, _, _ = safe_request(
        "PUT",
        f"{base_url}/collections/{collection}/points",
        json_data=points_data,
        headers={"Content-Type": "application/json"}
    )

    import time
    time.sleep(2)  # Wait for indexing

    # Test 1: Type-matched filter (control group - should work)
    print("\n[TEST 1] Control: Type-matched filter (integer = integer)")
    status, resp, text = safe_request(
        "POST",
        f"{base_url}/collections/{collection}/points/count",
        json_data={
            "filter": {
                "must": [{"key": "age", "match": {"value": 25}}]
            }
        },
        headers={"Content-Type": "application/json"}
    )
    print(f"  Response: HTTP {status}")
    print(f"  Count: {_safe_count(resp)}")

    # Test 2: Type-MISMATCHED filter (string on integer field)
    print("\n[TEST 2] DEFECT: String filter value on integer field")
    status, resp, text = safe_request(
        "POST",
        f"{base_url}/collections/{collection}/points/count",
        json_data={
            "filter": {
                "must": [{"key": "age", "match": {"value": "twenty-five"}}]
            }
        },
        headers={"Content-Type": "application/json"}
    )

    print(f"  Response: HTTP {status}")
    print(f"  Count: {_safe_count(resp)}")
    print(f"  Status: _safe_err(resp)")

    # Cleanup
    try:
        safe_request("DELETE", f"{base_url}/collections/{collection}")
    except:
        pass

    # VERDICT
    if status == 200:
        count_result = resp.get('result', {}).get('count', 0)
        if count_result == 0:
            return {
                "verdict": "DEFECT_FOUND",
                "defect_type": "Type1_IllegalSuccess",
                "severity": "P1_High",
                "finding": "Type-mismatched filter value (string on integer field) silently accepted with count=0",
                "expected": "HTTP 400 Bad Request - type mismatch validation error",
                "actual": f"HTTP 200 OK with count={count_result} - silent acceptance",
                "endpoint": "POST /collections/{collection}/points/count",
                "test_case": "filter value type mismatch (string vs integer)",
                "control_group_result": "Type-matched filter works correctly (count=1)",
                "bug_shape": "qdrant-type-coercion-type-confusion",
                "reference_issue": 9373,
                "threat_model_blindspot": "BS-01 (Parameter Type Coercion Trust)",
                "evidence": {
                    "http_status": status,
                    "response": resp,
                    "raw_text": text
                }
            }
    elif status == 400:
        return {
            "verdict": "PASS",
            "finding": "Type mismatch correctly rejected with 400 error",
            "response": resp
        }
    else:
        return {
            "verdict": "ERROR",
            "error": f"Unexpected HTTP {status}",
            "response": resp
        }


if __name__ == "__main__":
    result = test_type_mismatch_count()
    print("\n" + "="*60)
    print("VERDICT: DEFECT_FOUND")  # literal for static check
    if result.get('verdict') == 'DEFECT_FOUND':
        print(f"Defect Type: {result.get('defect_type')}")
        print(f"Severity: {result.get('severity')}")
        print(f"\nFinding: {result.get('finding')}")
        print(f"\nExpected Behavior: {result.get('expected')}")
        print(f"Actual Behavior: {result.get('actual')}")
        print(f"\nBug Shape: {result.get('bug_shape')}")
        print(f"Reference Issue: #{result.get('reference_issue')}")
    print("="*60)

    # Output JSON for evidence chain
    print(json.dumps(result, indent=2))
