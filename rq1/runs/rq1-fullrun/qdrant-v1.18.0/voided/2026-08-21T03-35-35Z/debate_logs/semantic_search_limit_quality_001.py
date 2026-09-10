#!/usr/bin/env python3
"""
Attack: qdrant_range_search_points_001 - Type-2 diagnosis quality
Target: Error message quality for invalid limit values (negative, zero, >1000)
Strategy: diagnosis_quality
"""
import os, sys, json, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

def safe_request(method, endpoint, json=None, timeout=10):
    """Safe HTTP request wrapper returning (status, body, raw)"""
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(method, url, json=json, headers=headers, timeout=timeout)
        status = response.status_code
        raw = response.text
        try:
            body = response.json()
        except:
            body = raw
        return status, body, raw
    except Exception as e:
        return -1, str(e), str(e)

COLLECTION = "test_search_limit_quality"
VECTOR_DIM = 128

def setup():
    """Create test collection"""
    try:
        safe_request("DELETE", f"/collections/{COLLECTION}")
    except:
        pass

    status, body, raw = safe_request("PUT", f"/collections/{COLLECTION}", json={
        "vectors": {
            "size": VECTOR_DIM,
            "distance": "Cosine"
        }
    })
    if status not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — setup failed: {status}")
        print(raw)
        sys.exit(2)

def teardown():
    """Cleanup test collection"""
    try:
        safe_request("DELETE", f"/collections/{COLLECTION}")
    except Exception:
        pass

def check_error_quality(status, body, raw, expected_param):
    """
    Type-2 diagnosis quality rubric:
    - Must mention the parameter name (1pt)
    - Should indicate correct format/range (1pt)
    - Bonus: actionable suggestion (1pt)
    """
    error_msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()
    error_msg += " " + raw.lower()

    score = 0
    max_score = 3

    # Criterion 1: Parameter named
    if expected_param.lower() in error_msg:
        score += 1

    # Criterion 2: Format/range hint
    format_hints = ["must be", "expected", "should be", "valid", "range", "type", "positive", "non-zero", "between", "greater", "less"]
    if any(hint in error_msg for hint in format_hints):
        score += 1

    # Criterion 3: Actionable suggestion
    action_hints = ["correct", "try", "use", "change", "specify", "provide", "set"]
    if any(hint in error_msg for hint in action_hints):
        score += 1

    return score, max_score

def test_invalid_limit_errors():
    """
    Test error message quality for invalid limit values.
    Contract qdrant_range_search_points_001: limit >= 1 and limit <= 1000
    """
    setup()

    # Test cases with invalid limits
    invalid_limits = [
        (-1, "negative"),
        (0, "zero"),
        (1001, "exceeds_max"),
        (9999, "far_exceeds_max")
    ]

    all_passed = True
    worst_score = 3

    for limit_val, label in invalid_limits:
        status, body, raw = safe_request("POST", f"/collections/{COLLECTION}/points/search", json={
            "vector": [0.1] * VECTOR_DIM,
            "limit": limit_val
        })

        print(f"\n--- Testing limit={limit_val} ({label}) ---")
        print(raw)

        # Should reject invalid input
        if status == 200:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)")
            print(f"limit={limit_val} should be rejected but was accepted")
            teardown()
            sys.exit(1)

        # Check error quality
        score, max_score = check_error_quality(status, body, raw, "limit")
        print(f"Error quality score: {score}/{max_score}")

        if score < 2:
            all_passed = False
        if score < worst_score:
            worst_score = score

    if not all_passed:
        print(f"\nVERDICT: DEFECT_FOUND (Type2_PoorDiagnostics)")
        print(f"Worst error quality score: {worst_score}/3")
        print("Expected parameter name + format hint for limit errors")
        teardown()
        sys.exit(1)

    print("\nVERDICT: NO_DEFECT")
    teardown()

if __name__ == "__main__":
    test_invalid_limit_errors()
