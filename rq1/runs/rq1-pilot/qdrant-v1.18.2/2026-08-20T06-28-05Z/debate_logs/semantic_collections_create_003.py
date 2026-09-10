"""
Test: Error Diagnosis Quality - Invalid Vector Size
Attack: Diagnosis Quality (Type-2)
Verifies error message quality when vectors.size is invalid
"""
import os
import sys
import json
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

def safe_request(method, endpoint, json_data=None, timeout=10):
    """Safe HTTP request wrapper with unified error handling."""
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.request(
            method=method,
            url=url,
            json=json_data,
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

def check_error_quality(status, body, expected_param):
    """
    Type-2 diagnosis quality rubric:
    - Must mention the parameter name
    - Should indicate correct format
    - Bonus: actionable suggestion
    """
    error_msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()

    score = 0
    max_score = 3

    # Criterion 1: Parameter named
    if expected_param.lower() in error_msg:
        score += 1

    # Criterion 2: Format/range hint
    format_hints = ["must be", "expected", "should be", "valid", "range", "type", "positive", "non-zero", "greater than"]
    if any(hint in error_msg for hint in format_hints):
        score += 1

    # Criterion 3: Actionable suggestion
    action_hints = ["correct", "try", "use", "change", "specify", "provide", "set"]
    if any(hint in error_msg for hint in action_hints):
        score += 1

    return score, max_score

def test_invalid_vector_size_error():
    """Verify error message quality for invalid vector.size"""
    collection_name = "test_invalid_size"

    # Test with invalid size (zero)
    test_cases = [
        {"size": 0, "desc": "zero"},
        {"size": -10, "desc": "negative"},
        {"size": 1.5, "desc": "float"},
    ]

    overall_quality_score = 0

    for test_case in test_cases:
        size_val = test_case["size"]
        desc = test_case["desc"]

        print(f"\nTesting invalid size: {size_val} ({desc})")

        payload = {
            "vectors": {
                "size": size_val,
                "distance": "Cosine"
            }
        }

        status, body, raw = safe_request(
            "PUT",
            f"/collections/{collection_name}",
            json_data=payload
        )

        print(f"Response status: {status}")
        print(f"Response body: {raw}")

        # Should get an error (400 or similar)
        if status == 200 or status == 201:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)")
            print(f"Invalid size {size_val} was incorrectly accepted")
            try:
                safe_request("DELETE", f"/collections/{collection_name}")
            except:
                pass
            sys.exit(1)

        # Check error quality
        score, max_score = check_error_quality(status, body, "size")
        overall_quality_score += score

        print(f"Error quality score: {score}/{max_score}")
        if score < 2:
            print(f"WARNING: Poor error quality for {desc} size (score={score}/{max_score})")

    # Average score check
    avg_score = overall_quality_score / len(test_cases)
    print(f"\nAverage error quality score: {avg_score:.2f}/{3:.0f}")

    if avg_score < 1.5:
        print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics)")
        print(f"Error messages for invalid vector.size lack diagnostic quality (avg score {avg_score:.2f})")
        sys.exit(1)

    print("VERDICT: NO_DEFECT")
    print("Error messages for invalid vector.size have acceptable diagnostic quality")

if __name__ == "__main__":
    test_invalid_vector_size_error()
