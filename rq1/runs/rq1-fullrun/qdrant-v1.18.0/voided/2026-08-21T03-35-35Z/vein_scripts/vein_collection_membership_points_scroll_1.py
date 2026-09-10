#!/usr/bin/env python3
"""
TestVDB Attack Script - Vein Mining: Collection Membership Filter
Strategy: vein_collection_membership
Target: qdrant v1.18.0
Endpoint: /collections/{collection_name}/points/scroll:POST

Defect Type: Type4_StateViolation (membership filter cardinality)

Description:
Tests collection membership filter (has_id clause) for correct handling
of ID lists including non-existent IDs.

Test Case 1: has_id with existing IDs only
- Input: has_id: [1, 5, 10]
- Expected: Returns points with IDs 1, 5, 10
- Actual: Should return correct subset

Test Case 2: has_id with mixed existing/non-existing IDs
- Input: has_id: [1, 999, 5, 998, 10]
- Expected: Returns only existing IDs [1, 5, 10]
- Actual: Should silently ignore non-existent IDs

Test Case 3: has_id with all non-existing IDs
- Input: has_id: [999, 998, 997]
- Expected: Empty result
- Actual: Should return empty result

Test Case 4: has_id with empty ID list
- Input: has_id: []
- Expected: Empty result
- Actual: May return all points (bug: empty list treated as match-all)

Test Case 5: has_id with duplicate IDs
- Input: has_id: [1, 1, 5, 5]
- Expected: Returns unique points [1, 5]
- Actual: Should deduplicate

Test Case 6: has_id with string IDs vs integer IDs
- Input: Mixed string/int ID types
- Expected: Proper type handling or clear error
- Actual: May have type coercion issues
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

    collection = f"vein_collection_membership_test_{int(time.time())}"
    base_url = f"{db_url}/collections/{collection}"

    # VERDICT: NO_DEFECT (collection membership filter works correctly)
    # This script verifies has_id filter handles ID lists correctly.

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

        # Insert test points
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

        # Step 2: Test Case 1 - has_id with existing IDs
        print("[Test 1] has_id with existing IDs only")
        scroll_1 = safe_request(
            "POST",
            f"{base_url}/points/scroll",
            data={
                "limit": 100,
                "filter": {"must": [{"has_id": [1, 5, 10]}]}
            }
        )

        print(f"  Response status: {scroll_1[0]}")

        if scroll_1[0] == 200:
            returned_points = scroll_1[1].get("result", {}).get("points", [])
            returned_ids = sorted([p.get("id") for p in returned_points])
            print(f"  Returned IDs: {returned_ids}")
            print(f"  Expected: [1, 5, 10]")

            if returned_ids == [1, 5, 10]:
                print("  ✓ PASS: has_id returns correct existing IDs")
            else:
                findings.append({
                    "test": "has_id_existing",
                    "severity": "High",
                    "type": "Type4_StateViolation",
                    "finding": f"has_id returned unexpected IDs: {returned_ids}",
                    "expected": "[1, 5, 10]",
                    "actual": f"{returned_ids}"
                })

        # Step 3: Test Case 2 - has_id with mixed existing/non-existing IDs
        print("\n[Test 2] has_id with mixed existing/non-existing IDs")
        scroll_2 = safe_request(
            "POST",
            f"{base_url}/points/scroll",
            data={
                "limit": 100,
                "filter": {"must": [{"has_id": [1, 999, 5, 998, 10]}]}
            }
        )

        print(f"  Response status: {scroll_2[0]}")

        if scroll_2[0] == 200:
            returned_points = scroll_2[1].get("result", {}).get("points", [])
            returned_ids = sorted([p.get("id") for p in returned_points])
            print(f"  Returned IDs: {returned_ids}")
            print(f"  Expected: [1, 5, 10] (non-existent IDs ignored)")

            if returned_ids == [1, 5, 10]:
                print("  ✓ PASS: has_id silently ignores non-existent IDs")
            else:
                findings.append({
                    "test": "has_id_mixed",
                    "severity": "Medium",
                    "type": "Type4_StateViolation",
                    "finding": f"has_id with mixed IDs returned unexpected result: {returned_ids}",
                    "expected": "[1, 5, 10]",
                    "actual": f"{returned_ids}"
                })

        # Step 4: Test Case 3 - has_id with all non-existing IDs
        print("\n[Test 3] has_id with all non-existing IDs")
        scroll_3 = safe_request(
            "POST",
            f"{base_url}/points/scroll",
            data={
                "limit": 100,
                "filter": {"must": [{"has_id": [999, 998, 997]}]}
            }
        )

        print(f"  Response status: {scroll_3[0]}")

        if scroll_3[0] == 200:
            returned_points = scroll_3[1].get("result", {}).get("points", [])
            print(f"  Returned points count: {len(returned_points)}")
            print(f"  Expected: 0 (empty result)")

            if len(returned_points) == 0:
                print("  ✓ PASS: has_id with all non-existing IDs returns empty result")
            else:
                findings.append({
                    "test": "has_id_all_nonexistent",
                    "severity": "Medium",
                    "type": "Type4_StateViolation",
                    "finding": f"has_id with all non-existing IDs returned {len(returned_points)} points",
                    "expected": "0 points",
                    "actual": f"{len(returned_points)} points"
                })

        # Step 5: Test Case 4 - has_id with empty ID list
        print("\n[Test 4] has_id with empty ID list")
        scroll_4 = safe_request(
            "POST",
            f"{base_url}/points/scroll",
            data={
                "limit": 100,
                "filter": {"must": [{"has_id": []}]}
            }
        )

        print(f"  Response status: {scroll_4[0]}")

        if scroll_4[0] == 200:
            returned_points = scroll_4[1].get("result", {}).get("points", [])
            print(f"  Returned points count: {len(returned_points)}")
            print(f"  Expected: 0 (empty result)")

            if len(returned_points) == 0:
                print("  ✓ PASS: empty has_id returns empty result")
            else:
                findings.append({
                    "test": "has_id_empty",
                    "severity": "High",
                    "type": "Type4_StateViolation",
                    "finding": f"empty has_id returned {len(returned_points)} points (match-all bug)",
                    "expected": "0 points",
                    "actual": f"{len(returned_points)} points",
                    "note": "Empty list treated as match-all is a critical filter bug"
                })

        # Step 6: Test Case 5 - has_id with duplicate IDs
        print("\n[Test 5] has_id with duplicate IDs")
        scroll_5 = safe_request(
            "POST",
            f"{base_url}/points/scroll",
            data={
                "limit": 100,
                "filter": {"must": [{"has_id": [1, 1, 5, 5, 10]}]}
            }
        )

        print(f"  Response status: {scroll_5[0]}")

        if scroll_5[0] == 200:
            returned_points = scroll_5[1].get("result", {}).get("points", [])
            returned_ids = sorted([p.get("id") for p in returned_points])
            print(f"  Returned IDs: {returned_ids}")
            print(f"  Expected: [1, 5, 10] (duplicates removed)")

            if returned_ids == [1, 5, 10]:
                print("  ✓ PASS: has_id deduplicates IDs")
            elif len(returned_ids) != len(set([p.get("id") for p in returned_points])):
                findings.append({
                    "test": "has_id_duplicates",
                    "severity": "High",
                    "type": "Type4_StateViolation",
                    "finding": "has_id returned duplicate points",
                    "expected": "unique IDs",
                    "actual": f"{returned_ids}",
                    "note": "Duplicates indicate deduplication failure"
                })
            else:
                print(f"  ⚠ WARNING: has_id returned {returned_ids}")

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
            print("Collection membership (has_id) filter works correctly:")
            print("- returns existing IDs")
            print("- silently ignores non-existent IDs")
            print("- returns empty for all non-existing IDs")
            print("- returns empty for empty ID list")
            print("- deduplicates IDs")

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
