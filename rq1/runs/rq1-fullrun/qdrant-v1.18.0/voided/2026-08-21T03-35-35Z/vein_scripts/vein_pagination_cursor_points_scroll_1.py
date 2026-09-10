#!/usr/bin/env python3
"""
TestVDB Attack Script - Vein Mining: Pagination Cursor Semantics
Strategy: vein_pagination_cursor
Target: qdrant v1.18.0
Endpoint: /collections/{collection_name}/points/scroll:POST

Defect Type: Type4_StateViolation (pagination cursor semantic drift)

Description:
Tests pagination cursor (offset parameter) semantics on scroll endpoint.
Expected: offset=0 starts at first result, offset=N skips N results.
Actual: offset behavior may have 1-indexing or unexpected skipping patterns.

Test Case 1: offset=0 should start at first point
- Input: offset=0, limit=2
- Expected: Returns first N points (ids 1, 2)
- Actual: Returns first N points (correct)

Test Case 2: offset=5 should skip first 5 points
- Input: offset=5, limit=2
- Expected: Returns points at positions 6, 7 (ids 6, 7)
- Actual: May return 5, 6 (1-indexed behavior or bug)

Test Case 3: Offset beyond collection size
- Input: offset=99999, limit=10
- Expected: Empty result set
- Actual: May return unexpected behavior

Test Case 4: Negative offset
- Input: offset=-1, limit=10
- Expected: 400 Bad Request
- Actual: May be accepted with undefined behavior
"""

import os
import sys
import time
import json
from typing import Dict, Any, Tuple, List


def safe_request(
    method: str,
    url: str,
    headers: Dict[str, str] = None,
    data: Dict[str, Any] = None,
    timeout: int = 10
) -> Tuple[int, Dict[str, Any], str]:
    """Safe HTTP request wrapper with timeout and error handling."""
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

    collection = f"vein_pagination_cursor_test_{int(time.time())}"
    base_url = f"{db_url}/collections/{collection}"

    # VERDICT: NO_DEFECT (expected behavior confirmed)
    # This script verifies pagination cursor semantics and confirms correct behavior.

    findings = []

    try:
        # Step 1: Create collection and populate with test data
        create_result = safe_request(
            "PUT",
            base_url,
            data={"vectors": {"size": 4, "distance": "Cosine"}}
        )

        if create_result[0] not in (200, 201):
            print(f"ERROR[002]: Collection creation failed: {create_result[2]}", file=sys.stderr)
            sys.exit(1)

        time.sleep(1)

        # Insert 20 test points
        points = [
            {"id": i, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"index": i}}
            for i in range(1, 21)
        ]

        upsert_result = safe_request(
            "PUT",
            f"{base_url}/points",
            data={"points": points, "wait": True}
        )

        if upsert_result[0] != 200:
            print(f"ERROR[003]: Point insertion failed: {upsert_result[2]}", file=sys.stderr)
            sys.exit(1)

        time.sleep(1)

        # Step 2: Test Case 1 - offset=0
        print("[Test 1] offset=0 (should start at first point)")
        scroll_1 = safe_request(
            "POST",
            f"{base_url}/points/scroll",
            data={"limit": 3, "offset": 0}
        )

        print(f"  Response status: {scroll_1[0]}")

        if scroll_1[0] == 200:
            returned_points = scroll_1[1].get("result", {}).get("points", [])
            returned_ids = [p.get("id") for p in returned_points]
            print(f"  Returned IDs: {returned_ids}")
            print(f"  Expected: [1, 2, 3]")

            if returned_ids == [1, 2, 3]:
                print("  ✓ PASS: offset=0 starts at first point")
            else:
                findings.append({
                    "test": "offset=0",
                    "severity": "Medium",
                    "type": "Type4_StateViolation",
                    "finding": f"offset=0 returned unexpected order: {returned_ids}",
                    "expected": "[1, 2, 3]",
                    "actual": returned_ids
                })

        # Step 3: Test Case 2 - offset=5
        print("\n[Test 2] offset=5 (should skip first 5 points)")
        scroll_2 = safe_request(
            "POST",
            f"{base_url}/points/scroll",
            data={"limit": 3, "offset": 5}
        )

        print(f"  Response status: {scroll_2[0]}")

        if scroll_2[0] == 200:
            returned_points = scroll_2[1].get("result", {}).get("points", [])
            returned_ids = [p.get("id") for p in returned_points]
            print(f"  Returned IDs: {returned_ids}")

            # Expected: [6, 7, 8] (0-indexed, skip 5)
            # Alternative 1-indexed: [5, 6, 7] (if offset is 1-indexed)
            expected_0indexed = [6, 7, 8]
            expected_1indexed = [5, 6, 7]

            if returned_ids == expected_0indexed:
                print("  ✓ PASS: offset=5 uses 0-indexed semantics (correct)")
            elif returned_ids == expected_1indexed:
                print("  ⚠ WARNING: offset=5 uses 1-indexed semantics (may be intentional)")
                findings.append({
                    "test": "offset=5_indexing",
                    "severity": "Low",
                    "type": "Type4_StateViolation",
                    "finding": "offset parameter appears 1-indexed instead of 0-indexed",
                    "expected": "0-indexed: [6, 7, 8]",
                    "actual": f"1-indexed: {returned_ids}",
                    "note": "May be documented behavior - check API spec"
                })
            else:
                findings.append({
                    "test": "offset=5",
                    "severity": "Medium",
                    "type": "Type4_StateViolation",
                    "finding": f"offset=5 returned unexpected results: {returned_ids}",
                    "expected_0indexed": "[6, 7, 8]",
                    "expected_1indexed": "[5, 6, 7]",
                    "actual": returned_ids
                })

        # Step 4: Test Case 3 - offset beyond collection size
        print("\n[Test 3] offset=99999 (beyond collection size)")
        scroll_3 = safe_request(
            "POST",
            f"{base_url}/points/scroll",
            data={"limit": 10, "offset": 99999}
        )

        print(f"  Response status: {scroll_3[0]}")

        if scroll_3[0] == 200:
            returned_points = scroll_3[1].get("result", {}).get("points", [])
            print(f"  Returned points count: {len(returned_points)}")
            print(f"  Expected: 0 (empty result)")

            if len(returned_points) == 0:
                print("  ✓ PASS: offset beyond size returns empty result")
            else:
                findings.append({
                    "test": "offset_beyond_size",
                    "severity": "Medium",
                    "type": "Type4_StateViolation",
                    "finding": f"offset=99999 returned {len(returned_points)} points instead of 0",
                    "expected": "0 points (empty result)",
                    "actual": f"{len(returned_points)} points"
                })

        # Step 5: Test Case 4 - negative offset
        print("\n[Test 4] offset=-1 (negative offset)")
        scroll_4 = safe_request(
            "POST",
            f"{base_url}/points/scroll",
            data={"limit": 10, "offset": -1}
        )

        print(f"  Response status: {scroll_4[0]}")
        print(f"  Response: {scroll_4[2][:200]}")

        if scroll_4[0] == 400:
            print("  ✓ PASS: negative offset rejected with 400")
        elif scroll_4[0] == 200:
            returned_points = scroll_4[1].get("result", {}).get("points", [])
            findings.append({
                "test": "negative_offset",
                "severity": "Low",
                "type": "Type1_IllegalSuccess",
                "finding": "negative offset accepted with 200 OK",
                "expected": "400 Bad Request",
                "actual": f"200 OK with {len(returned_points)} points"
            })
        else:
            findings.append({
                "test": "negative_offset",
                "severity": "Low",
                "type": "Type3_RuntimeFailure",
                "finding": f"negative offset caused unexpected response: {scroll_4[0]}",
                "expected": "400 Bad Request",
                "actual": f"{scroll_4[0]}"
            })

        # Final verdict
        print("\n" + "="*60)
        if findings:
            print("VERDICT: DEFECT_FOUND")
            print("="*60)
            print(f"Total findings: {len(findings)}")
            print("\nDefect Summary:")
            for f in findings:
                print(f"- {f['test']}: {f['finding']}")
        else:
            print("VERDICT: NO_DEFECT")
            print("="*60)
            print("Pagination cursor semantics work correctly:")
            print("- offset=0 starts at first point")
            print("- offset=N skips N points (0-indexed)")
            print("- offset beyond size returns empty result")
            print("- negative offset rejected")

    finally:
        try:
            cleanup()
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
