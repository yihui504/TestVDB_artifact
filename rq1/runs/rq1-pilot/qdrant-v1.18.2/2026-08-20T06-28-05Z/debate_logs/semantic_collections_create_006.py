"""
Test: Error Diagnosis Quality - Invalid Distance Metric
Attack: Diagnosis Quality (Type-2)
Verifies error message quality when vectors.distance is invalid
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
    format_hints = ["must be", "expected", "should be", "valid", "one of", "allowed", "values"]
    if any(hint in error_msg for hint in format_hints):
        score += 1

    # Criterion 3: Actionable suggestion or list of valid values
    action_hints = ["correct", "try", "use", "change", "specify", "cosine", "euclidean", "dot", "manhattan"]
    if any(hint in error_msg for hint in action_hints):
        score += 1

    return score, max_score

def test_invalid_distance_error():
    """Verify error message quality for invalid vectors.distance"""
    collection_name = "test_invalid_distance"

    # Valid values per contract: Cosine, Euclidean, Dot, Manhattan
    invalid_distances = [
        "InvalidMetric",
        "cosine",  # lowercase (case sensitivity test)
        "Jaccard",
        "Hamming",
        "",
        123,
        None,
        True,
    ]

    overall_quality_score = 0
    test_count = 0

    for distance_val in invalid_distances:
        print(f"\nTesting invalid distance: {distance_val} (type: {type(distance_val).__name__})")

        payload = {
            "vectors": {
                "size": 128,
                "distance": distance_val
            }
        }

        status, body, raw = safe_request(
            "PUT",
            f"/collections/{collection_name}",
            json_data=payload
        )

        print(f"Response status: {status}")
        print(f"Response body: {raw[:200] if raw else 'empty'}")

        # Should get an error (400 or similar)
        if status == 200 or status == 201:
            print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)")
            print(f"Invalid distance '{distance_val}' was incorrectly accepted")
            try:
                safe_request("DELETE", f"/collections/{collection_name}")
            except:
                pass
            sys.exit(1)

        # Check error quality
        score, max_score = check_error_quality(status, body, "distance")
        overall_quality_score += score
        test_count += 1

        print(f"Error quality score: {score}/{max_score}")
        if score < 2:
            print(f"WARNING: Poor error quality for '{distance_val}' (score={score}/{max_score})")

    if test_count > 0:
        avg_score = overall_quality_score / test_count
        print(f"\nAverage error quality score: {avg_score:.2f}/{3:.0f}")

        if avg_score < 1.5:
            print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics)")
            print(f"Error messages for invalid distance lack diagnostic quality (avg score {avg_score:.2f})")
            sys.exit(1)

    print("VERDICT: NO_DEFECT")
    print("Error messages for invalid vectors.distance have acceptable diagnostic quality")

if __name__ == "__main__":
    test_invalid_distance_error()
