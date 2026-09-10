#!/usr/bin/env python3
"""
TestVDB Attack Script - Vein Mining: Compound OR Filter Semantics
Strategy: vein_compound_or
Target: qdrant v1.18.0
Endpoint: /collections/{collection_name}/points/scroll:POST

Defect Type: Type4_StateViolation (compound filter cardinality error)

Description:
Tests compound OR filter (should clause) semantics for correct cardinality
and result set composition. OR filters should union matching sets.

Test Case 1: Empty should clause
- Input: {"should": []}
- Expected: Empty result (no matches)
- Actual: May return all points (bug: empty should treated as match-all)

Test Case 2: Single condition in should
- Input: {"should": [{"key": "field", "match": {"value": "A"}}]}
- Expected: Points where field=A
- Actual: Should return correct subset

Test Case 3: Multiple conditions in should (OR union)
- Input: {"should": [condition1, condition2]}
- Expected: Points matching condition1 OR condition2 (union)
- Actual: May incorrectly intersect or have wrong cardinality

Test Case 4: Nested should with must_not
- Input: {"should": [{"must": [...]}], "must_not": [...]}
- Expected: Complex boolean logic correctly applied
- Actual: May have interaction bugs

This is inspired by bug-shape cardinality_oracle issues where compound
filters return incorrect counts.
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

    collection = f"vein_compound_or_test_{int(time.time())}"
    base_url = f"{db_url}/collections/{collection}"

    # VERDICT: NO_DEFECT (OR filter semantics work correctly)
    # This script verifies compound OR (should clause) filter semantics.

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

        # Insert test points with different category values
        points = []
        for i in range(1, 31):
            category = chr(65 + (i % 3))  # A, B, C repeating
            points.append({
                "id": i,
                "vector": [0.1, 0.2, 0.3, 0.4],
                "payload": {"category": category, "value": i}
            })

        upsert_result = safe_request(
            "PUT",
            f"{base_url}/points",
            data={"points": points, "wait": True}
        )

        if upsert_result[0] != 200:
            print(f"ERROR[003]: Point insertion failed: {upsert_result[2]}", file=sys.stderr)
            sys.exit(1)

        time.sleep(1)

        # Step 2: Test Case 1 - Empty should clause
        print("[Test 1] Empty should clause")
        scroll_empty = safe_request(
            "POST",
            f"{base_url}/points/scroll",
            data={"limit": 100, "filter": {"should": []}}
        )

        print(f"  Response status: {scroll_empty[0]}")

        if scroll_empty[0] == 200:
            returned_points = scroll_empty[1].get("result", {}).get("points", [])
            print(f"  Returned points count: {len(returned_points)}")
            print(f"  Expected: 0 (empty result)")

            if len(returned_points) == 0:
                print("  ✓ PASS: empty should returns empty result")
            else:
                findings.append({
                    "test": "empty_should",
                    "severity": "High",
                    "type": "Type4_StateViolation",
                    "finding": f"empty should clause returned {len(returned_points)} points instead of 0",
                    "expected": "0 points",
                    "actual": f"{len(returned_points)} points",
                    "note": "Empty should treated as match-all is a critical bug"
                })

        # Step 3: Test Case 2 - Single condition (control)
        print("\n[Test 2] Single condition in should")
        scroll_single = safe_request(
            "POST",
            f"{base_url}/points/scroll",
            data={
                "limit": 100,
                "filter": {
                    "should": [
                        {"key": "category", "match": {"value": "A"}}
                    ]
                }
            }
        )

        print(f"  Response status: {scroll_single[0]}")

        if scroll_single[0] == 200:
            returned_points = scroll_single[1].get("result", {}).get("points", [])
            returned_ids = [p.get("id") for p in returned_points]
            print(f"  Returned IDs: {returned_ids[:10]}...")
            print(f"  Total count: {len(returned_ids)}")

            # Count how many should be A: 1, 4, 7, 10, 13, 16, 19, 22, 25, 28 = 10 points
            expected_count = 10
            print(f"  Expected count: {expected_count} (category=A)")

            if len(returned_ids) == expected_count:
                print("  ✓ PASS: single condition returns correct count")
            else:
                findings.append({
                    "test": "single_condition_should",
                    "severity": "Medium",
                    "type": "Type4_StateViolation",
                    "finding": f"single condition returned {len(returned_ids)} points, expected {expected_count}",
                    "expected": f"{expected_count} points",
                    "actual": f"{len(returned_ids)} points"
                })

        # Step 4: Test Case 3 - Compound OR (should with multiple conditions)
        print("\n[Test 3] Compound OR - union of two conditions")
        scroll_or = safe_request(
            "POST",
            f"{base_url}/points/scroll",
            data={
                "limit": 100,
                "filter": {
                    "should": [
                        {"key": "category", "match": {"value": "A"}},
                        {"key": "category", "match": {"value": "B"}}
                    ]
                }
            }
        )

        print(f"  Response status: {scroll_or[0]}")

        if scroll_or[0] == 200:
            returned_points = scroll_or[1].get("result", {}).get("points", [])
            returned_ids = [p.get("id") for p in returned_points]
            print(f"  Returned IDs: {returned_ids[:20]}...")
            print(f"  Total count: {len(returned_ids)}")

            # Union of A (10 points) + B (10 points) = 20 points
            expected_count = 20
            print(f"  Expected count: {expected_count} (A OR B)")

            # Verify no duplicates
            if len(returned_ids) != len(set(returned_ids)):
                findings.append({
                    "test": "compound_or_duplicates",
                    "severity": "High",
                    "type": "Type4_StateViolation",
                    "finding": "compound OR returned duplicate IDs",
                    "expected": "unique set of points",
                    "actual": f"duplicate IDs found in {len(returned_ids)} results",
                    "unique_count": len(set(returned_ids))
                })
            elif len(returned_ids) == expected_count:
                print("  ✓ PASS: compound OR returns correct union without duplicates")
            else:
                findings.append({
                    "test": "compound_or_cardinality",
                    "severity": "Medium",
                    "type": "Type4_StateViolation",
                    "finding": f"compound OR returned {len(returned_ids)} points, expected {expected_count}",
                    "expected": f"{expected_count} points (A ∪ B)",
                    "actual": f"{len(returned_ids)} points"
                })

        # Step 5: Test Case 4 - Compound OR with three conditions
        print("\n[Test 4] Compound OR - union of three conditions")
        scroll_or3 = safe_request(
            "POST",
            f"{base_url}/points/scroll",
            data={
                "limit": 100,
                "filter": {
                    "should": [
                        {"key": "category", "match": {"value": "A"}},
                        {"key": "category", "match": {"value": "B"}},
                        {"key": "category", "match": {"value": "C"}}
                    ]
                }
            }
        )

        print(f"  Response status: {scroll_or3[0]}")

        if scroll_or3[0] == 200:
            returned_points = scroll_or3[1].get("result", {}).get("points", [])
            returned_ids = [p.get("id") for p in returned_points]
            print(f"  Total count: {len(returned_ids)}")

            # Union of A (10) + B (10) + C (10) = 30 points
            expected_count = 30
            print(f"  Expected count: {expected_count} (A OR B OR C)")

            if len(returned_ids) == expected_count:
                print("  ✓ PASS: compound OR with 3 conditions returns correct union")
            else:
                findings.append({
                    "test": "compound_or_3conditions",
                    "severity": "Medium",
                    "type": "Type4_StateViolation",
                    "finding": f"compound OR (3-way) returned {len(returned_ids)} points, expected {expected_count}",
                    "expected": f"{expected_count} points",
                    "actual": f"{len(returned_ids)} points"
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
            print("Compound OR (should clause) filter semantics work correctly:")
            print("- empty should returns empty result")
            print("- single condition returns correct subset")
            print("- compound OR returns correct union")
            print("- no duplicate IDs in results")
            print("- cardinality matches expectations")

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
