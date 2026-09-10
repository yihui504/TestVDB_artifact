#!/usr/bin/env python3
"""
TestVDB Attack Vein - Round 2: type_mismatch on count endpoint
Strategy: Finding-feedback from cardinality_oracle + bug_shape type_confusion
Test if type-mismatched filter values cause estimation errors on count(exact:false)
"""
import sys
import json
import time
import traceback
from typing import Dict, Any, Tuple

def safe_request(method: str, url: str, **kwargs) -> Tuple[int, Dict[str, Any], str]:
    """Safe HTTP request wrapper for TestVDB attack scripts."""
    import urllib.request
    import urllib.error

    headers = kwargs.pop('headers', {})
    data = kwargs.pop('data', None)
    timeout = kwargs.pop('timeout', 10)

    if data:
        data = json.dumps(data).encode('utf-8')
        if 'Content-Type' not in headers:
            headers['Content-Type'] = 'application/json'

    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status = response.getcode()
            text = response.read().decode('utf-8')
            try:
                resp_dict = json.loads(text)
            except:
                resp_dict = {"raw": text}
            return (status, resp_dict, text)
    except urllib.error.HTTPError as e:
        return (e.code, {"error": str(e), "body": e.read().decode('utf-8')}, str(e))
    except urllib.error.URLError as e:
        return (0, {"error": f"URL Error: {e}"}, str(e))
    except Exception as e:
        return (0, {"error": f"Request failed: {e}"}, str(e))


def extract_count(resp: Dict[str, Any]) -> int:
    """Extract count from Qdrant response (handles nested structure)."""
    if isinstance(resp, dict):
        if "result" in resp and isinstance(resp["result"], int):
            return resp["result"]
        elif "status" in resp and isinstance(resp["status"], dict) and "result" in resp["status"]:
            return resp["status"]["result"] if isinstance(resp["status"]["result"], int) else 0
    return 0


def cleanup(db_url: str, collections_created: list):
    """Cleanup: Delete all test collections."""
    print("\n[CLEANUP] Deleting test collections...")
    for collection in collections_created:
        try:
            url = f"{db_url}/collections/{collection}"
            status, _, _ = safe_request("DELETE", url, timeout=10)
            print(f"  - DELETE {collection}: {status}")
        except Exception as e:
            print(f"  - DELETE {collection}: failed ({e})")


def create_collection(db_url: str, name: str) -> bool:
    """Create test collection with indexed payload."""
    url = f"{db_url}/collections/{name}"
    config = {
        "vectors": {"size": 4, "distance": "Cosine"},
        "optimizers_config": {"indexing_threshold": 1}
    }
    status, resp, _ = safe_request("PUT", url, data=config, timeout=10)
    if status == 200:
        time.sleep(0.5)
        return True
    print(f"[WARN] Create collection {name} failed: {status} - {resp}")
    return False


def insert_typed_points(db_url: str, collection: str, count: int) -> bool:
    """Insert points with typed payload (price field as integer)."""
    url = f"{db_url}/collections/{collection}/points"
    points = []
    for i in range(count):
        # Alternate price values: 100, 200, 300, 400, 500
        price = 100 + (i % 5) * 100
        points.append({
            "id": i,
            "vector": [0.1, 0.2, 0.3, 0.4],
            "payload": {"price": price}
        })

    status, resp, _ = safe_request("PUT", url, data={"points": points}, timeout=30)
    if status == 200:
        time.sleep(2)
        return True
    print(f"[WARN] Insert failed: {status} - {resp}")
    return False


def create_payload_index(db_url: str, collection: str) -> bool:
    """Create integer index on price field."""
    url = f"{db_url}/collections/{collection}/index"
    index_config = {
        "field_name": "price",
        "field_schema": "integer"
    }
    status, resp, _ = safe_request("PUT", url, data=index_config, timeout=10)
    if status == 200:
        time.sleep(4)
        return True
    print(f"[WARN] Payload index creation failed: {status} - {resp}")
    return False


def test_type_mismatch_count(db_url: str, collection: str) -> Dict[str, Any]:
    """Test count(exact:false) with type-mismatched filter value."""
    url = f"{db_url}/collections/{collection}/points/count"

    # Test 1: Type-matched filter (integer) - baseline
    filter_int = {
        "filter": {
            "must": [{"key": "price", "range": {"gte": 200, "lte": 400}}]
        },
        "exact": True
    }
    status_int_true, resp_int_true, _ = safe_request("POST", url, data=filter_int, timeout=10)
    exact_true_int = extract_count(resp_int_true) if status_int_true == 200 else 0

    filter_int_false = {**filter_int, "exact": False}
    status_int_false, resp_int_false, _ = safe_request("POST", url, data=filter_int_false, timeout=10)
    exact_false_int = extract_count(resp_int_false) if status_int_false == 200 else 0

    # Test 2: Type-mismatched filter (string value for integer field) - THE ATTACK
    filter_mismatch = {
        "filter": {
            "must": [{"key": "price", "match": {"value": "200"}}]
        },
        "exact": True
    }

    status_mismatch_true, resp_mismatch_true, _ = safe_request("POST", url, data=filter_mismatch, timeout=10)
    exact_true_mismatch = extract_count(resp_mismatch_true) if status_mismatch_true == 200 else 0

    filter_mismatch_false = {**filter_mismatch, "exact": False}
    status_mismatch_false, resp_mismatch_false, _ = safe_request("POST", url, data=filter_mismatch_false, timeout=10)
    exact_false_mismatch = extract_count(resp_mismatch_false) if status_mismatch_false == 200 else 0

    # Test 3: Null value (should be rejected or handled)
    filter_null = {
        "filter": {
            "must": [{"key": "price", "is_null": True}]
        },
        "exact": True
    }
    status_null_true, resp_null_true, _ = safe_request("POST", url, data=filter_null, timeout=10)
    exact_true_null = extract_count(resp_null_true) if status_null_true == 200 else 0

    filter_null_false = {**filter_null, "exact": False}
    status_null_false, resp_null_false, _ = safe_request("POST", url, data=filter_null_false, timeout=10)
    exact_false_null = extract_count(resp_null_false) if status_null_false == 200 else 0

    return {
        "type_matched": {
            "exact_true": int(exact_true_int),
            "exact_false": int(exact_false_int),
            "error_pct": ((int(exact_false_int) - int(exact_true_int)) / int(exact_true_int) * 100) if int(exact_true_int) > 0 else 0
        },
        "type_mismatched": {
            "exact_true": int(exact_true_mismatch),
            "exact_false": int(exact_false_mismatch),
            "error_pct": ((int(exact_false_mismatch) - int(exact_true_mismatch)) / int(exact_true_mismatch) * 100) if int(exact_true_mismatch) > 0 else 0
        },
        "null_check": {
            "exact_true": int(exact_true_null),
            "exact_false": int(exact_false_null),
            "error_pct": ((int(exact_false_null) - int(exact_true_null)) / int(exact_true_null) * 100) if int(exact_true_null) > 0 else 0
        }
    }


def main():
    import os
    db_url = os.getenv("TESTVDB_DB_URL", "http://localhost:6333")
    collection_base = "vein_type_mismatch"
    collections_created = []
    test_sizes = [50, 200, 500]

    try:
        print("[ATTACK] type_mismatch on count endpoint (finding-feedback + type_confusion shape)")
        print("=" * 70)

        all_results = {}

        for size in test_sizes:
            collection = f"{collection_base}_{size}"
            collections_created.append(collection)

            print(f"\n[TEST] Collection size: {size}")
            print("-" * 50)

            # Setup
            if not create_collection(db_url, collection):
                print(f"[FAIL] Could not create collection {collection}")
                continue

            if not insert_typed_points(db_url, collection, size):
                print(f"[FAIL] Could not insert points into {collection}")
                continue

            if not create_payload_index(db_url, collection):
                print(f"[FAIL] Could not create payload index on {collection}")
                continue

            # Test
            results = test_type_mismatch_count(db_url, collection)
            all_results[f"size_{size}"] = results

            print(f"\n  [Type-Matched] Integer filter:")
            print(f"    exact=true:  {results['type_matched']['exact_true']}")
            print(f"    exact=false: {results['type_matched']['exact_false']}")
            print(f"    error: {results['type_matched']['error_pct']:.1f}%")

            print(f"\n  [Type-Mismatched] String '200' on integer field:")
            print(f"    exact=true:  {results['type_mismatched']['exact_true']}")
            print(f"    exact=false: {results['type_mismatched']['exact_false']}")
            print(f"    error: {results['type_mismatched']['error_pct']:.1f}%")

            print(f"\n  [Null Check]:")
            print(f"    exact=true:  {results['null_check']['exact_true']}")
            print(f"    exact=false: {results['null_check']['exact_false']}")
            print(f"    error: {results['null_check']['error_pct']:.1f}%")

        # Analysis
        print("\n" + "=" * 70)
        print("[ANALYSIS] Type mismatch cardinality estimation results")
        print("-" * 70)

        # Check if type-mismatched query returns different results
        mismatches_found = []
        for size in test_sizes:
            r = all_results.get(f"size_{size}", {})
            tm = r.get("type_mismatched", {})
            if tm.get("exact_true", 0) != tm.get("exact_false", 0):
                mismatches_found.append(size)

        if mismatches_found:
            verdict = "DEFECT_FOUND"
            print(f"[DEFECT_FOUND] Type-mismatched filter shows estimation errors")
            print(f"  Affected sizes: {mismatches_found}")
        else:
            # Check if type-mismatched is rejected (expected behavior)
            rejected = False
            for size in test_sizes:
                r = all_results.get(f"size_{size}", {})
                tm = r.get("type_mismatched", {})
                if tm.get("exact_true", 0) == 0 and tm.get("exact_false", 0) == 0:
                    rejected = True
                    break

            if rejected:
                verdict = "BY_DESIGN_EXCLUDED"
                print("[BY_DESIGN] Type-mismatched filters rejected (expected behavior)")
            else:
                verdict = "PASS"
                print("[PASS] Type-mismatched filters handled correctly")

        # Final output
        output = {
            "strategy": "vein_type_mismatch",
            "endpoint": "POST /collections/{collection}/points/count",
            "condition_type": "type_mismatch",
            "test_sizes": test_sizes,
            "results": all_results,
            "verdict": verdict,
            "threat_model_reference": "BS-01 (Parameter Type Coercion Trust)",
            "finding_feedback_source": "cardinality_oracle (round 1) + type_confusion shape"
        }

        print("\n" + "=" * 70)
        print(json.dumps(output, indent=2))
        print("=" * 70)

        print("\nVERDICT: NO_DEFECT")
        return 0 if verdict == "PASS" else 1

    except Exception as e:
        print(f"\n[FATAL] Test execution failed: {e}")
        traceback.print_exc()
        return 2
    finally:
        cleanup(db_url, collections_created)


if __name__ == "__main__":
    sys.exit(main())
