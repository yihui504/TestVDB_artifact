"""
Test: Error Diagnosis Quality - Missing Required Parameters
Attack: Diagnosis Quality (Type-2)
Verifies error message quality when required parameters are missing
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

def check_error_quality(status, body, expected_params):
    """
    Type-2 diagnosis quality rubric:
    - Must mention the parameter name
    - Should indicate correct format
    - Bonus: actionable suggestion
    """
    error_msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()

    score = 0
    max_score = 3

    # Criterion 1: At least one required parameter named
    if any(param.lower() in error_msg for param in expected_params):
        score += 1

    # Criterion 2: Format/range hint (required, missing, must be)
    format_hints = ["required", "missing", "must be", "expected", "should be", "provide", "specify"]
    if any(hint in error_msg for hint in format_hints):
        score += 1

    # Criterion 3: Actionable suggestion or field name mention
    action_hints = ["vectors", "size", "distance", "field", "parameter"]
    if any(hint in error_msg for hint in action_hints):
        score += 1

    return score, max_score

def test_missing_parameters_error():
    """Verify error message quality for missing required parameters"""
    collection_name = "test_missing_params"

    # Test cases with missing required parameters
    test_cases = [
        {
            "name": "missing_vectors",
            "payload": {},
            "missing": ["vectors"],
            "desc": "Missing vectors object (required)"
        },
        {
            "name": "missing_vectors_size",
            "payload": {"vectors": {"distance": "Cosine"}},
            "missing": ["size"],
            "desc": "Missing vectors.size (required)"
        },
        {
            "name": "missing_vectors_distance",
            "payload": {"vectors": {"size": 128}},
            "missing": ["distance"],
            "desc": "Missing vectors.distance (required)"
        },
        {
            "name": "empty_vectors",
            "payload": {"vectors": {}},
            "missing": ["size", "distance"],
            "desc": "Empty vectors object"
        },
    ]

    overall_quality_score = 0
    test_count = 0

    for test_case in test_cases:
        print(f"\n{'='*60}")
        print(f"Test: {test_case['name']}")
        print(f"Description: {test_case['desc']}")
        print(f"Payload: {test_case['payload']}")

        status, body, raw = safe_request(
            "PUT",
            f"/collections/{collection_name}",
            json_data=test_case["payload"]
        )

        print(f"Response status: {status}")
        print(f"Response body: {raw[:300] if raw else 'empty'}")

        # Should get an error (400 or similar)
        if status == 200 or status == 201:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)")
            print(f"Missing parameters were incorrectly accepted: {test_case['missing']}")
            try:
                safe_request("DELETE", f"/collections/{collection_name}")
            except:
                pass
            sys.exit(1)

        # Check error quality
        score, max_score = check_error_quality(status, body, test_case["missing"])
        overall_quality_score += score
        test_count += 1

        print(f"Error quality score: {score}/{max_score}")
        if score < 2:
            print(f"WARNING: Poor error quality (score={score}/{max_score})")
            print(f"Expected to mention: {test_case['missing']}")

    if test_count > 0:
        avg_score = overall_quality_score / test_count
        print(f"\n{'='*60}")
        print(f"Average error quality score: {avg_score:.2f}/{3:.0f}")

        if avg_score < 1.5:
            print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics)")
            print(f"Error messages for missing parameters lack diagnostic quality")
            print(f"(average score {avg_score:.2f} < 1.5 threshold)")
            sys.exit(1)

    print("\nVERDICT: NO_DEFECT")
    print("Error messages for missing required parameters have acceptable diagnostic quality")

if __name__ == "__main__":
    test_missing_parameters_error()
