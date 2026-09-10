#!/usr/bin/env python3
"""
TestVDB Attack Vein - Compound And Condition - Schema Pairing Invariants

Defect: POST /v1/schema accepts inverted pairing (dynamicEfMin > dynamicEfMax),
negative values, zero, and extreme values without validation.

Expected: Server should reject requests where dynamicEfMin > dynamicEfMax,
negative values, zero, or unreasonably extreme values for dynamicEfMin/dynamicEfMax
and flatSearchCutoff parameters.

Strategy: vein_compound_and
Condition Type: compound_and (pairing invariants)
"""

import requests
import json
import time
from typing import Dict, Any, Tuple

def safe_request(method: str, url: str, **kwargs) -> Tuple[Dict[str, Any], int, str]:
    """
    Safe HTTP request wrapper with timeout and error handling.

    Args:
        method: HTTP method (GET, POST, PUT, DELETE, PATCH)
        url: Target URL
        **kwargs: Additional arguments for requests

    Returns:
        Tuple of (response_json, status_code, error_message)
    """
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
    # Clean up any existing test collections
    for name in ["VeinPairTest", "VeinPairNegTest", "VeinPairZeroTest", "VeinPairExtremeTest"]:
        safe_request("DELETE", f"{base_url}/v1/schema/{name}")
        time.sleep(0.1)
    return True

def cleanup(base_url: str):
    """Cleanup test collections."""
    for name in ["VeinPairTest", "VeinPairNegTest", "VeinPairZeroTest", "VeinPairExtremeTest"]:
        safe_request("DELETE", f"{base_url}/v1/schema/{name}")

def test_pairing_inverted(base_url: str) -> Tuple[bool, str]:
    """Test: Inverted pairing (Min > Max)"""
    collection_name = "VeinPairTest"
    payload = {
        "class": collection_name,
        "vectorIndexConfig": {
            "dynamicEfMin": 500,
            "dynamicEfMax": 100
        }
    }

    resp, status, err = safe_request(
        "POST",
        f"{base_url}/v1/schema",
        headers={"Content-Type": "application/json"},
        json=payload
    )

    if status == 200 or status == 201:
        # Check if values were actually stored inverted
        stored_min = resp.get("vectorIndexConfig", {}).get("dynamicEfMin", 0)
        stored_max = resp.get("vectorIndexConfig", {}).get("dynamicEfMax", 0)
        if stored_min == 500 and stored_max == 100:
            return False, f"DEFECT: Server accepts inverted pairing (Min=500 > Max=100) without validation"
        return True, "UNEXPECTED: Server stored different values"
    elif status >= 400:
        return True, f"OK: Server rejected inverted pairing with {status}"
    else:
        return False, f"ERROR: Unexpected status {status}"

def test_pairing_negative(base_url: str) -> Tuple[bool, str]:
    """Test: Negative values for both parameters"""
    collection_name = "VeinPairNegTest"
    payload = {
        "class": collection_name,
        "vectorIndexConfig": {
            "dynamicEfMin": -100,
            "dynamicEfMax": -500
        }
    }

    resp, status, err = safe_request(
        "POST",
        f"{base_url}/v1/schema",
        headers={"Content-Type": "application/json"},
        json=payload
    )

    if status == 200 or status == 201:
        stored_min = resp.get("vectorIndexConfig", {}).get("dynamicEfMin", 0)
        stored_max = resp.get("vectorIndexConfig", {}).get("dynamicEfMax", 0)
        if stored_min == -100 and stored_max == -500:
            return False, f"DEFECT: Server accepts negative values (Min=-100, Max=-500) without validation"
        return True, "UNEXPECTED: Server stored different values"
    elif status >= 400:
        return True, f"OK: Server rejected negative values with {status}"
    else:
        return False, f"ERROR: Unexpected status {status}"

def test_pairing_zero(base_url: str) -> Tuple[bool, str]:
    """Test: Zero values for both parameters"""
    collection_name = "VeinPairZeroTest"
    payload = {
        "class": collection_name,
        "vectorIndexConfig": {
            "dynamicEfMin": 0,
            "dynamicEfMax": 0
        }
    }

    resp, status, err = safe_request(
        "POST",
        f"{base_url}/v1/schema",
        headers={"Content-Type": "application/json"},
        json=payload
    )

    if status == 200 or status == 201:
        stored_min = resp.get("vectorIndexConfig", {}).get("dynamicEfMin", 0)
        stored_max = resp.get("vectorIndexConfig", {}).get("dynamicEfMax", 0)
        if stored_min == 0 and stored_max == 0:
            return False, f"DEFECT: Server accepts zero values for EF parameters without validation"
        return True, "UNEXPECTED: Server stored different values"
    elif status >= 400:
        return True, f"OK: Server rejected zero values with {status}"
    else:
        return False, f"ERROR: Unexpected status {status}"

def test_pairing_extreme(base_url: str) -> Tuple[bool, str]:
    """Test: Extreme positive values"""
    collection_name = "VeinPairExtremeTest"
    payload = {
        "class": collection_name,
        "vectorIndexConfig": {
            "dynamicEfMin": 999999999,
            "dynamicEfMax": 999999999
        }
    }

    resp, status, err = safe_request(
        "POST",
        f"{base_url}/v1/schema",
        headers={"Content-Type": "application/json"},
        json=payload
    )

    if status == 200 or status == 201:
        stored_min = resp.get("vectorIndexConfig", {}).get("dynamicEfMin", 0)
        stored_max = resp.get("vectorIndexConfig", {}).get("dynamicEfMax", 0)
        if stored_min == 999999999 and stored_max == 999999999:
            return False, f"DEFECT: Server accepts extreme values (999999999) without validation"
        return True, "UNEXPECTED: Server stored different values"
    elif status >= 400:
        return True, f"OK: Server rejected extreme values with {status}"
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
            ("Inverted Pairing", test_pairing_inverted),
            ("Negative Values", test_pairing_negative),
            ("Zero Values", test_pairing_zero),
            ("Extreme Values", test_pairing_extreme),
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
            print(f"\nVERDICT: {VERDICT} - {defect_count} defect(s) found in pairing invariant validation")
        else:
            VERDICT = "NO_DEFECT"
            print(f"\nVERDICT: {VERDICT} - All pairing invariant tests passed")

    finally:
        # Cleanup
        cleanup(base_url)

if __name__ == "__main__":
    main()
