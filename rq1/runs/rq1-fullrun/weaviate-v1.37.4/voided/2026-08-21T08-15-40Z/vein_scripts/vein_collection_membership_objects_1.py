#!/usr/bin/env python3
"""
TestVDB Attack Vein - Collection Membership Condition - Objects Endpoint

Defect: POST /v1/objects accepts references to non-existent collections and
invalid tenant associations without validation.

Expected: Server should reject requests where the class doesn't exist or
tenant doesn't belong to the collection.

Strategy: vein_collection_membership
Condition Type: collection_membership
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
    """Setup test environment by creating test collections."""
    # Ensure we have a valid collection for control tests
    payload = {"class": "VeinMembershipTest"}
    resp, status, _ = safe_request("POST", f"{base_url}/v1/schema",
                                  headers={"Content-Type": "application/json"},
                                  json=payload)
    time.sleep(0.5)
    return True

def cleanup(base_url: str):
    """Cleanup test collections."""
    for name in ["VeinMembershipTest", "NonexistentCollection"]:
        safe_request("DELETE", f"{base_url}/v1/schema/{name}")

def test_nonexistent_class(base_url: str) -> Tuple[bool, str]:
    """Test: Object creation with non-existent class"""
    payload = {
        "class": "NonexistentCollection",
        "properties": {"name": "test_object"}
    }

    resp, status, err = safe_request(
        "POST",
        f"{base_url}/v1/objects",
        headers={"Content-Type": "application/json"},
        json=payload
    )

    if status == 200 or status == 201:
        if "id" in resp:
            return False, "DEFECT: Server accepts objects for non-existent class without validation, creating implicit collection"
        return True, "UNEXPECTED: Response missing id"
    elif status >= 400:
        return True, f"OK: Server rejected non-existent class with {status}"
    else:
        return False, f"ERROR: Unexpected status {status}"

def test_nonexistent_tenant(base_url: str) -> Tuple[bool, str]:
    """Test: Object creation with non-existent tenant"""
    payload = {
        "class": "VeinMembershipTest",
        "properties": {"name": "test_object"},
        "tenant": "NonexistentTenant12345"
    }

    resp, status, err = safe_request(
        "POST",
        f"{base_url}/v1/objects",
        headers={"Content-Type": "application/json"},
        json=payload
    )

    if status == 200 or status == 201:
        if "id" in resp:
            return False, "DEFECT: Server accepts objects with non-existent tenant without validation, creating implicit tenant or ignoring parameter"
        return True, "UNEXPECTED: Response missing id"
    elif status >= 400:
        return True, f"OK: Server rejected non-existent tenant with {status}"
    else:
        return False, f"ERROR: Unexpected status {status}"

def test_empty_class_name(base_url: str) -> Tuple[bool, str]:
    """Test: Object creation with empty class name"""
    payload = {
        "class": "",
        "properties": {"name": "test_object"}
    }

    resp, status, err = safe_request(
        "POST",
        f"{base_url}/v1/objects",
        headers={"Content-Type": "application/json"},
        json=payload
    )

    if status == 200 or status == 201:
        if "id" in resp:
            return False, "DEFECT: Server accepts objects with empty class name without validation"
        return True, "UNEXPECTED: Response missing id"
    elif status >= 400:
        return True, f"OK: Server rejected empty class name with {status}"
    else:
        return False, f"ERROR: Unexpected status {status}"

def test_special_chars_class(base_url: str) -> Tuple[bool, str]:
    """Test: Object creation with special characters in class name"""
    payload = {
        "class": "Test/Class/With/Slashes",
        "properties": {"name": "test_object"}
    }

    resp, status, err = safe_request(
        "POST",
        f"{base_url}/v1/objects",
        headers={"Content-Type": "application/json"},
        json=payload
    )

    if status == 200 or status == 201:
        if "id" in resp:
            return False, "DEFECT: Server accepts objects with special characters in class name without validation"
        return True, "UNEXPECTED: Response missing id"
    elif status >= 400:
        return True, f"OK: Server rejected special characters in class name with {status}"
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
            ("Non-existent Class", test_nonexistent_class),
            ("Non-existent Tenant", test_nonexistent_tenant),
            ("Empty Class Name", test_empty_class_name),
            ("Special Characters Class", test_special_chars_class),
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
            print(f"\nVERDICT: {VERDICT} - {defect_count} defect(s) found in collection membership validation")
        else:
            VERDICT = "NO_DEFECT"
            print(f"\nVERDICT: {VERDICT} - All collection membership tests passed")

    finally:
        # Cleanup
        cleanup(base_url)

if __name__ == "__main__":
    main()
