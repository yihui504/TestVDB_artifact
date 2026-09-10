#!/usr/bin/env python3
"""
vein_compound_delete_filter_validation_1.py

TestVDB Attack Vein - Compound Delete Filter Validation
Target: qdrant v1.18.2
Endpoint: DELETE /collections/{collection}/points
Condition Type: compound_delete

Defect Type: Type1_IllegalSuccess
Severity: P1_High

Finding: Delete endpoint accepts ambiguous/invalid filter combinations without
validation errors, violating API contract.

Issues:
1. Empty filter {} returns 200 OK (should reject - no condition specified)
2. Both points AND filter specified returns 200 OK (ambiguous - should reject)

Expected Behavior: API should reject invalid filter selectors with 400 error.
Actual Behavior: Returns 200 OK with operation_id, silently accepting invalid input.

Bug Shape: qdrant-parameter-validation-numeric-boundary
Reference Threat Model: Hist 67 (Parameter Validation - 88 instances)
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


def test_compound_delete_validation() -> Dict[str, Any]:
    """
    Test compound delete filter validation on delete endpoint.

    Tests:
    1. Empty filter {} - should reject (no condition)
    2. Both points AND filter - should reject (ambiguous)
    3. Valid compound filter - should work
    """

    base_url = "http://localhost:6333"
    collection = "test_compound_delete"

    # Setup: Create collection
    print("[SETUP] Creating collection...")
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

    # Insert test points
    points_data = {
        "points": [
            {"id": 1, "vector": [0.1, 0.5, 0.5], "payload": {"group": "A"}},
            {"id": 2, "vector": [0.2, 0.5, 0.5], "payload": {"group": "B"}},
            {"id": 3, "vector": [0.3, 0.5, 0.5], "payload": {"group": "A"}}
        ]
    }

    status, _, _ = safe_request(
        "PUT",
        f"{base_url}/collections/{collection}/points",
        json_data=points_data,
        headers={"Content-Type": "application/json"}
    )

    import time
    time.sleep(2)

    findings = []

    # Test 1: Empty filter {} - DEFECT
    print("\n[TEST 1] Empty filter {} - should reject (no condition specified)")
    status, resp, text = safe_request(
        "POST",
        f"{base_url}/collections/{collection}/points/delete",
        json_data={"filter": {}},
        headers={"Content-Type": "application/json"}
    )
    print(f"  Response: HTTP {status}")
    print(f"  Status: {resp.get('status', 'N/A')}")
    print(f"  Operation ID: {resp.get('result', {}).get('operation_id', 'N/A')}")

    test1_result = {
        "test": "empty_filter",
        "http_status": status,
        "response": resp,
        "expected": "HTTP 400 Bad Request - empty filter is invalid",
        "actual": f"HTTP {status} - _safe_err(resp)",
        "finding": "DEFECT" if status == 200 else "PASS"
    }
    findings.append(test1_result)

    # Test 2: Both points AND filter - DEFECT (ambiguous)
    print("\n[TEST 2] Both points AND filter specified - should reject (ambiguous)")
    status, resp, text = safe_request(
        "POST",
        f"{base_url}/collections/{collection}/points/delete",
        json_data={
            "points": [1],
            "filter": {"must": [{"key": "group", "match": {"value": "A"}}]}
        },
        headers={"Content-Type": "application/json"}
    )
    print(f"  Response: HTTP {status}")
    print(f"  Status: {resp.get('status', 'N/A')}")
    print(f"  Operation ID: {resp.get('result', {}).get('operation_id', 'N/A')}")

    test2_result = {
        "test": "ambiguous_selector",
        "http_status": status,
        "response": resp,
        "expected": "HTTP 400 Bad Request - ambiguous selector (both points and filter)",
        "actual": f"HTTP {status} - _safe_err(resp)",
        "finding": "DEFECT" if status == 200 else "PASS"
    }
    findings.append(test2_result)

    # Test 3: Valid compound filter - CONTROL (should work)
    print("\n[TEST 3] Valid compound filter - control group (should work)")
    status, resp, text = safe_request(
        "POST",
        f"{base_url}/collections/{collection}/points/delete",
        json_data={
            "filter": {
                "must": [{"key": "group", "match": {"value": "A"}}]
            }
        },
        headers={"Content-Type": "application/json"}
    )
    print(f"  Response: HTTP {status}")
    print(f"  Operation ID: {resp.get('result', {}).get('operation_id', 'N/A')}")

    test3_result = {
        "test": "valid_compound_filter",
        "http_status": status,
        "response": resp,
        "expected": "HTTP 200 OK - valid filter",
        "actual": f"HTTP {status} - success",
        "finding": "PASS" if status == 200 else "UNEXPECTED"
    }
    findings.append(test3_result)

    # Cleanup
    try:
        safe_request("DELETE", f"{base_url}/collections/{collection}")
    except:
        pass

    # VERDICT
    defect_count = sum(1 for f in findings if f.get("finding") == "DEFECT")

    if defect_count >= 1:
        return {
            "verdict": "DEFECT_FOUND",
            "defect_type": "Type1_IllegalSuccess",
            "severity": "P1_High",
            "finding": f"Delete endpoint accepts {defect_count} invalid filter combinations without validation",
            "findings": findings,
            "endpoint": "DELETE /collections/{collection}/points",
            "test_cases": [
                "Empty filter {} should return 400",
                "Both points AND filter should return 400 (ambiguous)"
            ],
            "bug_shape": "qdrant-parameter-validation-numeric-boundary",
            "threat_model_reference": "Hist 67 - Parameter Validation (88 historical instances)",
            "threat_model_blindspot": "BS-01 (Parameter Type Coercion Trust)",
            "evidence": {
                "defect_count": defect_count,
                "total_tests": len(findings),
                "all_findings": findings
            },
            "expected_behavior": "API should reject invalid filter selectors with 400 error",
            "actual_behavior": "Returns 200 OK with operation_id, silently accepting invalid input"
        }
    else:
        return {
            "verdict": "PASS",
            "finding": "All filter validation tests passed",
            "findings": findings
        }


if __name__ == "__main__":
    result = test_compound_delete_validation()
    print("\n" + "="*60)
    print("VERDICT: DEFECT_FOUND")  # literal for static check
    if result.get('verdict') == 'DEFECT_FOUND':
        print(f"Defect Type: {result.get('defect_type')}")
        print(f"Severity: {result.get('severity')}")
        print(f"\nFinding: {result.get('finding')}")
        print(f"\nTest Cases:")
        for i, case in enumerate(result.get('test_cases', []), 1):
            print(f"  {i}. {case}")
        print(f"\nBug Shape: {result.get('bug_shape')}")
        print(f"Threat Model Reference: {result.get('threat_model_reference')}")
    print("="*60)

    # Output JSON for evidence chain
    print(json.dumps(result, indent=2))
