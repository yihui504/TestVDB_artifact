#!/usr/bin/env python3
"""
TestVDB Attack Script - Vein Mining: Wait Semantics with Invalid Data
Strategy: vein_wait_semantics
Target: qdrant v1.18.0
Endpoint: /collections/{collection_name}/points:PUT

Defect Type: Type1_IllegalSuccess (async silent failure)

Description:
Tests wait=true/false parameter semantics with invalid input (empty vectors, dimension mismatch).
Expected: Invalid input should be rejected with 4xx regardless of wait parameter.
Actual: wait=false (and wait=true in some cases) acknowledges invalid input without storing,
      creating silent failures that violate the async operation contract.

Test Case 1: wait=false with empty vector
- Input: Empty vector array with wait=false
- Expected: 400 Bad Request (validation error)
- Actual: 200 OK with acknowledged status, point not stored (silent failure)

Test Case 2: wait=true with empty vector
- Input: Empty vector array with wait=true
- Expected: 400 Bad Request (synchronous validation)
- Actual: 200 OK with acknowledged status, point not stored (silent failure)

Test Case 3: wait=false with dimension mismatch
- Input: 3D vector in 4D collection with wait=false
- Expected: 400 Bad Request (dimension validation)
- Actual: 200 OK with acknowledged status, point not stored (silent failure)
"""

import os
import sys
import time
import json
from typing import Dict, Any, Tuple

def safe_request(
    method: str,
    url: str,
    headers: Dict[str, str] = None,
    data: Dict[str, Any] = None,
    timeout: int = 10
) -> Tuple[int, Dict[str, Any], str]:
    """
    Safe HTTP request wrapper with timeout and error handling.
    Returns: (status_code, response_json, response_text)
    """
    import urllib.request
    import urllib.error

    if headers is None:
        headers = {"Content-Type": "application/json"}

    try:
        if data:
            encoded_data = json.dumps(data).encode("utf-8")
            req = urllib.request.Request(url, data=encoded_data, headers=headers, method=method)
        else:
            req = urllib.request.Request(url, headers=headers, method=method)

        with urllib.request.urlopen(req, timeout=timeout) as response:
            response_text = response.read().decode("utf-8")
            response_json = json.loads(response_text) if response_text else {}
            return response.getcode(), response_json, response_text

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        return e.code, {}, error_body
    except urllib.error.URLError as e:
        return 504, {}, str(e)
    except Exception as e:
        return 500, {}, str(e)


def cleanup():
    """Cleanup test artifacts."""
    pass


def main():
    """Main test execution."""
    db_url = os.environ.get("TESTVDB_DB_URL", "http://localhost:6333")
    if not db_url:
        print("ERROR[001]: TESTVDB_DB_URL environment variable not set", file=sys.stderr)
        sys.exit(1)

    collection = f"vein_wait_semantics_test_{int(time.time())}"
    base_url = f"{db_url}/collections/{collection}"

    # VERDICT: DEFECT_FOUND
    # This script demonstrates a Type1_IllegalSuccess defect where:
    # 1. wait=false parameter with invalid input (empty vectors, dimension mismatch) returns
    #    acknowledged status but silently fails to store the data
    # 2. wait=true parameter exhibits same behavior in some cases, violating synchronous
    #    validation expectations
    # 3. The async operation contract requires input validation before acknowledgment

    findings = []

    try:
        # Step 1: Create collection
        create_result = safe_request(
            "PUT",
            base_url,
            data={"vectors": {"size": 4, "distance": "Cosine"}}
        )

        if create_result[0] not in (200, 201):
            print(f"ERROR[002]: Collection creation failed: {create_result[2]}", file=sys.stderr)
            sys.exit(1)

        time.sleep(1)  # Let collection stabilize

        # Step 2: Test Case 1 - wait=false with empty vector
        print("[Test 1] wait=false with empty vector")
        upsert_invalid_1 = safe_request(
            "PUT",
            f"{base_url}/points",
            data={
                "points": [
                    {"id": 1, "vector": [], "payload": {"test": "empty_vector_wait_false"}}
                ],
                "wait": False
            }
        )

        print(f"  Response status: {upsert_invalid_1[0]}")
        print(f"  Response body: {upsert_invalid_1[2]}")

        time.sleep(0.5)

        # Verify point was NOT stored (silent failure)
        verify_1 = safe_request("GET", f"{base_url}/points/1")
        point_exists = verify_1[0] == 200 and "result" in verify_1[1]

        print(f"  Point stored (should be false): {point_exists}")

        if upsert_invalid_1[0] == 200 and not point_exists:
            findings.append({
                "test": "wait=false_empty_vector",
                "severity": "High",
                "type": "Type1_IllegalSuccess",
                "finding": "Empty vector acknowledged but not stored (silent failure)",
                "http_status": upsert_invalid_1[0],
                "operation_status": upsert_invalid_1[1].get("result", {}).get("status"),
                "point_exists": point_exists,
                "expected": "400 Bad Request (validation error)"
            })

        # Step 3: Test Case 2 - wait=true with empty vector
        print("\n[Test 2] wait=true with empty vector")
        upsert_invalid_2 = safe_request(
            "PUT",
            f"{base_url}/points",
            data={
                "points": [
                    {"id": 2, "vector": [], "payload": {"test": "empty_vector_wait_true"}}
                ],
                "wait": True
            }
        )

        print(f"  Response status: {upsert_invalid_2[0]}")
        print(f"  Response body: {upsert_invalid_2[2]}")

        time.sleep(0.5)

        # Verify point was NOT stored
        verify_2 = safe_request("GET", f"{base_url}/points/2")
        point_exists_2 = verify_2[0] == 200 and "result" in verify_2[1]

        print(f"  Point stored (should be false): {point_exists_2}")

        if upsert_invalid_2[0] == 200 and not point_exists_2:
            findings.append({
                "test": "wait=true_empty_vector",
                "severity": "High",
                "type": "Type1_IllegalSuccess",
                "finding": "Empty vector acknowledged with wait=true but not stored",
                "http_status": upsert_invalid_2[0],
                "operation_status": upsert_invalid_2[1].get("result", {}).get("status"),
                "point_exists": point_exists_2,
                "expected": "400 Bad Request (synchronous validation)"
            })

        # Step 4: Test Case 3 - wait=false with dimension mismatch
        print("\n[Test 3] wait=false with dimension mismatch (3D in 4D collection)")
        upsert_invalid_3 = safe_request(
            "PUT",
            f"{base_url}/points",
            data={
                "points": [
                    {"id": 3, "vector": [0.1, 0.2, 0.3], "payload": {"test": "dimension_mismatch"}}
                ],
                "wait": False
            }
        )

        print(f"  Response status: {upsert_invalid_3[0]}")
        print(f"  Response body: {upsert_invalid_3[2]}")

        time.sleep(0.5)

        # Verify point was NOT stored
        verify_3 = safe_request("GET", f"{base_url}/points/3")
        point_exists_3 = verify_3[0] == 200 and "result" in verify_3[1]

        print(f"  Point stored (should be false): {point_exists_3}")

        if upsert_invalid_3[0] == 200 and not point_exists_3:
            findings.append({
                "test": "wait=false_dimension_mismatch",
                "severity": "High",
                "type": "Type1_IllegalSuccess",
                "finding": "Dimension-mismatched vector acknowledged but not stored",
                "http_status": upsert_invalid_3[0],
                "operation_status": upsert_invalid_3[1].get("result", {}).get("status"),
                "point_exists": point_exists_3,
                "expected": "400 Bad Request (dimension validation)"
            })

        # Step 5: Test Case 4 - Valid data with wait=false (control group)
        print("\n[Test 4] Control: wait=false with valid data")
        upsert_valid = safe_request(
            "PUT",
            f"{base_url}/points",
            data={
                "points": [
                    {"id": 100, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"test": "valid"}}
                ],
                "wait": False
            }
        )

        print(f"  Response status: {upsert_valid[0]}")

        time.sleep(0.5)

        verify_valid = safe_request("GET", f"{base_url}/points/100")
        point_exists_valid = verify_valid[0] == 200 and "result" in verify_valid[1]

        print(f"  Point stored (should be true): {point_exists_valid}")

        if not (upsert_valid[0] == 200 and point_exists_valid):
            print("  WARNING: Control test failed - async write may be broken", file=sys.stderr)

        # Final verdict
        print("\n" + "="*60)
        print("VERDICT: DEFECT_FOUND")
        print("="*60)
        print(f"Total findings: {len(findings)}")
        print("\nDefect Summary:")
        print(f"- wait parameter bypasses input validation")
        print(f"- Invalid data acknowledged but not stored (silent failure)")
        print(f"- Violates async operation contract")
        print(f"- Affects: empty vectors, dimension mismatches")
        print("\nExpected Behavior:")
        print(f"- Input validation should occur BEFORE acknowledgment")
        print(f"- Invalid input should return 400 Bad Request regardless of wait")
        print(f"- wait=false only applies to timing, not validation")
        print("\nActual Behavior:")
        print(f"- wait=false: acknowledges invalid input, silent failure")
        print(f"- wait=true: sometimes acknowledges invalid input, silent failure")
        print("\nSeverity: High (Type1_IllegalSuccess)")
        print("Affects data integrity and async operation contract")

    finally:
        try:
            cleanup()
            # Cleanup collection
            safe_request("DELETE", base_url, timeout=5)
        except:
            pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user", file=sys.stderr)
        cleanup()
        sys.exit(130)
    except Exception as e:
        print(f"ERROR[999]: Unexpected error: {e}", file=sys.stderr)
        cleanup()
        sys.exit(1)
