#!/usr/bin/env python3
"""
Attack: qdrant_range_upsert_points_001 - Type-2 diagnosis quality
Target: Error message quality for invalid batch sizes (negative, zero, >1000)
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

COLLECTION = "test_upsert_batch_quality"
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
    """Type-2 diagnosis quality rubric"""
    error_msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()
    error_msg += " " + raw.lower()

    score = 0
    max_score = 3

    # Criterion 1: Parameter named
    if expected_param.lower() in error_msg or "batch" in error_msg or "points" in error_msg:
        score += 1

    # Criterion 2: Format/range hint
    format_hints = ["must be", "expected", "should be", "valid", "range", "type", "positive", "non-zero", "between", "maximum", "limit"]
    if any(hint in error_msg for hint in format_hints):
        score += 1

    # Criterion 3: Actionable suggestion
    action_hints = ["correct", "try", "use", "change", "specify", "provide", "set", "reduce"]
    if any(hint in error_msg for hint in action_hints):
        score += 1

    return score, max_score

def test_invalid_batch_sizes():
    """
    Test error message quality for invalid batch sizes.
    Contract qdrant_range_upsert_points_001: batch_size >= 1 and batch_size <= 1000
    """
    setup()

    # Test empty batch
    print("\n--- Testing empty batch (zero points) ---")
    status, body, raw = safe_request("PUT", f"/collections/{COLLECTION}/points", json={
        "points": []
    })
    print(raw)

    if status == 200:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)")
        print("Empty points array should be rejected but was accepted")
        teardown()
        sys.exit(1)

    score_empty, max_score = check_error_quality(status, body, raw, "points")
    print(f"Empty batch error quality: {score_empty}/{max_score}")

    # Test oversized batch (>1000 points)
    print("\n--- Testing oversized batch (1001 points) ---")
    large_batch = [{"id": i, "vector": [0.1] * VECTOR_DIM} for i in range(1001)]
    status, body, raw = safe_request("PUT", f"/collections/{COLLECTION}/points", json={
        "points": large_batch
    }, timeout=30)

    print(raw[:500])

    score_oversized, max_score = check_error_quality(status, body, raw, "points")
    print(f"Oversized batch error quality: {score_oversized}/{max_score}")

    worst_score = min(score_empty, score_oversized)

    if worst_score < 2:
        print(f"\nVERDICT: DEFECT_FOUND (Type2_PoorDiagnostics)")
        print(f"Worst error quality score: {worst_score}/3")
        print("Expected parameter name + format hint for batch size errors")
        teardown()
        sys.exit(1)

    print("\nVERDICT: NO_DEFECT")
    teardown()

if __name__ == "__main__":
    test_invalid_batch_sizes()
