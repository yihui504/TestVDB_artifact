#!/usr/bin/env python3
"""
Attack: state_consistency | create_special_names | name_validation
Strategy: 1 (CRUD后COUNT一致性 - 名称边界值测试)
Endpoint: collections+create
Constraint IDs:
  - type_constraints::qdrant_type_create_collection_001
  - behavioral_contracts::qdrant_behavioral_create_visibility_001
Source URL: https://api.qdrant.tech/api-reference/collections/create-collection
Doc Version: 1.19.x
Expected Defect Type: Type4_StateLogicViolation
Blindspot: BS-03 (Concurrency Blindness) - name state consistency
"""

import os
import sys
import time
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

def safe_request(method, endpoint, json=None, timeout=10):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text)
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.request(
            method=method,
            url=url,
            json=json,
            headers=headers,
            timeout=timeout
        )
        status_code = response.status_code
        raw_text = response.text

        try:
            body = response.json()
        except:
            body = raw_text

        return status_code, body, raw_text
    except Exception as e:
        return -1, str(e), str(e)

# Test cases: (name, should_succeed)
name_test_cases = [
    ("test_normal", True),
    ("test_123", True),
    ("TestCamelCase", True),
    ("test-hyphen", True),
    ("test_underscore", True),
    ("test.dot", True),
    ("Test123Numbers", True),
    ("a", True),  # Single char
    ("test_collection_with_very_long_name_0123456789_0123456789_0123456789", True),
    ("", False),  # Empty string
    ("test space", False),  # Space in name
    ("test/slash", False),  # Slash in name
    ("test\\backslash", False),  # Backslash
    ("test?question", False),  # Question mark
    ("test*asterisk", False),  # Asterisk
    ("test\"quote", False),  # Quote
    ("test'apostrophe", False),  # Apostrophe
    ("test<angle>", False),  # Angle brackets
    ("test|pipe", False),  # Pipe
    ("test:colon", False),  # Colon
]

create_body_template = {
    "vectors": {
        "size": 128,
        "distance": "Cosine"
    }
}

print(f"Testing {len(name_test_cases)} collection name patterns...")

results = []
errors = []

for test_name, should_succeed in name_test_cases:
    coll_name = test_name

    # Cleanup if exists
    try:
        safe_request("DELETE", f"/collections/{coll_name}")
        time.sleep(0.02)
    except Exception:
        pass

    # Try create
    status, body, raw = safe_request("PUT", f"/collections/{coll_name}", json=create_body_template)
    print(f"[{test_name}] status={status}, expected_success={should_succeed}")

    # Determine if this is an error
    is_error = False

    if should_succeed:
        if status != 200:
            is_error = True
            errors.append(f"'{test_name}' should succeed but got {status}")
        else:
            # Verify visibility
            status_g, _, raw_g = safe_request("GET", f"/collections/{coll_name}")
            if status_g != 200:
                is_error = True
                errors.append(f"'{test_name}' created but not visible (get={status_g})")

            # Cleanup successful creates
            try:
                safe_request("DELETE", f"/collections/{coll_name}")
            except Exception:
                pass
    else:
        if status == 200:
            is_error = True
            errors.append(f"'{test_name}' should fail but succeeded")

            # Cleanup unexpected success
            try:
                safe_request("DELETE", f"/collections/{coll_name}")
            except Exception:
                pass
        elif status != 400:
            errors.append(f"'{test_name}' should fail with 400 but got {status}")

    results.append((test_name, not is_error))
    time.sleep(0.02)

print(f"\nName validation results: {len(results)} tested")

if errors:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Name validation failures:")
    for err in errors[:5]:
        print(f"  - {err}")
    if len(errors) > 5:
        print(f"  ... and {len(errors) - 5} more")
    sys.exit(1)

success_rate = sum(1 for _, passed in results if passed) / len(results)
print(f"Success rate: {success_rate:.1%} ({sum(1 for _, passed in results if passed)}/{len(results)})")

if success_rate < 1.0:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Name validation consistency rate {success_rate:.1%} < 100%")
    sys.exit(1)

print(f"VERDICT: NO_DEFECT — All name validation tests passed")
sys.exit(0)
