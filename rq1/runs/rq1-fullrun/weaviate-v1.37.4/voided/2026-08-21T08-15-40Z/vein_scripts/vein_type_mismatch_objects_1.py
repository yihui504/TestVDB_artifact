#!/usr/bin/env python3
"""
TestVDB Attack Vein - Type Mismatch Condition - Objects Endpoint

Defect: POST /v1/objects accepts null, numeric, array, and object types for
consistencyLevel parameter without validation, silently coercing invalid values.

Expected: Server should reject requests where consistencyLevel is not a valid
string enum value (ONE, QUORUM, ALL).

Strategy: vein_type_mismatch
Condition Type: type_mismatch
"""

import requests
import json
import time
from typing import Dict, Any, Tuple

def safe_request(method: str, url: str, **kwargs) -> Tuple[Dict[str, Any], int, str]:
    """Safe HTTP request wrapper with timeout and error handling."""
    try:
        response = requests.request(
            method=method,
            url=url,
            timeout=10,
            **kwargs
        )
        response_json = {}
        try:
            response_json = response.json()
        except:
            response_json = {"raw_response": response.text}

        return response_json, response.status_code, ""
    except requests.exceptions.Timeout:
        return {}, 0, f"Request timeout after 10s"
    except requests.exceptions.ConnectionError as e:
        return {}, 0, f"Connection error: {str(e)}"
    except Exception as e:
        return {}, 0, f"Unexpected error: {str(e)}"

def setup_test_env(base_url: str) -> bool:
    """Setup test environment by ensuring test collections exist."""
    # Check if Nonexistent collection exists, create if not
    resp, status, _ = safe_request("GET", f"{base_url}/v1/schema/Nonexistent")
    if status == 404:
        # Create collection
        payload = {"class": "Nonexistent"}
        safe_request("POST", f"{base_url}/v1/schema",
                    headers={"Content-Type": "application/json"}, json=payload)
        time.sleep(0.5)
    return True

def test_null_consistency(base_url: str) -> Tuple[bool, str]:
    """Test: Null consistencyLevel"""
    payload = {
        "class": "Nonexistent",
        "properties": {"name": "test_object"},
        "consistencyLevel": None
    }

    resp, status, err = safe_request(
        "POST",
        f"{base_url}/v1/objects",
        headers={"Content-Type": "application/json"},
        json=payload
    )

    if status == 200 or status == 201:
        # Object created despite null consistencyLevel
        if "id" in resp:
            return False, "DEFECT: Server accepts null consistencyLevel without validation, silently coercing to default"
        return True, "UNEXPECTED: Response missing id"
    elif status >= 400:
        return True, f"OK: Server rejected null consistencyLevel with {status}"
    else:
        return False, f"ERROR: Unexpected status {status}"

def test_numeric_consistency(base_url: str) -> Tuple[bool, str]:
    """Test: Numeric consistencyLevel"""
    payload = {
        "class": "Nonexistent",
        "properties": {"name": "test_object"},
        "consistencyLevel": 999
    }

    resp, status, err = safe_request(
        "POST",
        f"{base_url}/v1/objects",
        headers={"Content-Type": "application/json"},
        json=payload
    )

    if status == 200 or status == 201:
        if "id" in resp:
            return False, "DEFECT: Server accepts numeric consistencyLevel without validation, silently coercing to default"
        return True, "UNEXPECTED: Response missing id"
    elif status >= 400:
        return True, f"OK: Server rejected numeric consistencyLevel with {status}"
    else:
        return False, f"ERROR: Unexpected status {status}"

def test_array_consistency(base_url: str) -> Tuple[bool, str]:
    """Test: Array consistencyLevel"""
    payload = {
        "class": "Nonexistent",
        "properties": {"name": "test_object"},
        "consistencyLevel": ["ONE", "QUORUM"]
    }

    resp, status, err = safe_request(
        "POST",
        f"{base_url}/v1/objects",
        headers={"Content-Type": "application/json"},
        json=payload
    )

    if status == 200 or status == 201:
        if "id" in resp:
            return False, "DEFECT: Server accepts array consistencyLevel without validation, silently coercing to default"
        return True, "UNEXPECTED: Response missing id"
    elif status >= 400:
        return True, f"OK: Server rejected array consistencyLevel with {status}"
    else:
        return False, f"ERROR: Unexpected status {status}"

def test_object_consistency(base_url: str) -> Tuple[bool, str]:
    """Test: Object consistencyLevel"""
    payload = {
        "class": "Nonexistent",
        "properties": {"name": "test_object"},
        "consistencyLevel": {"level": "ONE"}
    }

    resp, status, err = safe_request(
        "POST",
        f"{base_url}/v1/objects",
        headers={"Content-Type": "application/json"},
        json=payload
    )

    if status == 200 or status == 201:
        if "id" in resp:
            return False, "DEFECT: Server accepts object consistencyLevel without validation, silently coercing to default"
        return True, "UNEXPECTED: Response missing id"
    elif status >= 400:
        return True, f"OK: Server rejected object consistencyLevel with {status}"
    else:
        return False, f"ERROR: Unexpected status {status}"

def main():
    base_url = "http://localhost:8080"

    # Setup
    if not setup_test_env(base_url):
        print("Setup failed")
        return

    try:
        # Run tests
        tests = [
            ("Null Consistency", test_null_consistency),
            ("Numeric Consistency", test_numeric_consistency),
            ("Array Consistency", test_array_consistency),
            ("Object Consistency", test_object_consistency),
        ]

        results = []
        for test_name, test_func in tests:
            passed, message = test_func(base_url)
            results.append((test_name, passed, message))
            print(f"[{test_name}] {'PASS' if passed else 'FAIL'}: {message}")

        # Determine overall verdict
        all_passed = all(passed for _, passed, _ in results)
        if not all_passed:
            VERDICT = "DEFECT_FOUND"
            defect_count = sum(1 for _, passed, _ in results if not passed)
            print(f"\nVERDICT: {VERDICT} - {defect_count} defect(s) found in type mismatch validation")
        else:
            VERDICT = "NO_DEFECT"
            print(f"\nVERDICT: {VERDICT} - All type mismatch tests passed")

    finally:
        # No cleanup needed for objects tests
        pass

if __name__ == "__main__":
    main()
