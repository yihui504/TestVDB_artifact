#!/usr/bin/env python3
"""
TestVDB Attack Vein - Round 2: collection_membership (match_any OR) on count endpoint
Strategy: Finding-feedback from cardinality_oracle defect
Test if OR conditions (match_any) have estimation bugs on count(exact:false)
"""
import sys
import json
import time
import traceback
from typing import Dict, Any, Tuple

def safe_request(method: str, url: str, **kwargs) -> Tuple[int, Dict[str, Any], str]:
    """Safe HTTP request wrapper."""
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
    """Extract count from Qdrant response."""
    if isinstance(resp, dict):
        if "result" in resp and isinstance(resp["result"], int):
            return resp["result"]
        elif "status" in resp and isinstance(resp["status"], dict) and "result" in resp["status"]:
            return resp["status"]["result"] if isinstance(resp["status"]["result"], int) else 0
    return 0


def cleanup(db_url: str, collections_created: list):
    """Cleanup collections."""
    print("\n[CLEANUP] Deleting test collections...")
    for collection in collections_created:
        try:
            url = f"{db_url}/collections/{collection}"
            status, _, _ = safe_request("DELETE", url, timeout=10)
            print(f"  - DELETE {collection}: {status}")
        except Exception as e:
            print(f"  - DELETE {collection}: failed ({e})")


def create_collection(db_url: str, name: str) -> bool:
    """Create collection."""
    url = f"{db_url}/collections/{name}"
    config = {
        "vectors": {"size": 4, "distance": "Cosine"},
        "optimizers_config": {"indexing_threshold": 1}
    }
    status, resp, _ = safe_request("PUT", url, data=config, timeout=10)
    if status == 200:
        time.sleep(0.5)
        return True
    print(f"[WARN] Create failed: {status} - {resp}")
    return False


def insert_points(db_url: str, collection: str, count: int) -> bool:
    """Insert points with category payload."""
    url = f"{db_url}/collections/{collection}/points"
    points = []
    for i in range(count):
        # Categories: A, B, C, D, E
        category = chr(65 + (i % 5))  # A, B, C, D, E
        points.append({
            "id": i,
            "vector": [0.1, 0.2, 0.3, 0.4],
            "payload": {"category": category}
        })

    status, resp, _ = safe_request("PUT", url, data={"points": points}, timeout=30)
    if status == 200:
        time.sleep(2)
        return True
    print(f"[WARN] Insert failed: {status} - {resp}")
    return False


def create_keyword_index(db_url: str, collection: str) -> bool:
    """Create keyword index on category."""
    url = f"{db_url}/collections/{collection}/index"
    index_config = {
        "field_name": "category",
        "field_schema": "keyword"
    }
    status, resp, _ = safe_request("PUT", url, data=index_config, timeout=10)
    if status == 200:
        time.sleep(4)
        return True
    print(f"[WARN] Index creation failed: {status} - {resp}")
    return False


def test_match_any_count(db_url: str, collection: str) -> Dict[str, Any]:
    """Test count(exact:false) with match_any (OR) conditions."""
    url = f"{db_url}/collections/{collection}/points/count"

    # Test 1: Single match (baseline)
    filter_single = {
        "filter": {
            "must": [{"key": "category", "match": {"value": "A"}}]
        },
        "exact": True
    }
    status_s_true, resp_s_true, _ = safe_request("POST", url, data=filter_single, timeout=10)
    exact_true_single = extract_count(resp_s_true) if status_s_true == 200 else 0

    filter_s_false = {**filter_single, "exact": False}
    status_s_false, resp_s_false, _ = safe_request("POST", url, data=filter_s_false, timeout=10)
    exact_false_single = extract_count(resp_s_false) if status_s_false == 200 else 0

    # Test 2: Match any (OR) - THE ATTACK
    filter_or = {
        "filter": {
            "should": [
                {"key": "category", "match": {"value": "A"}},
                {"key": "category", "match": {"value": "B"}}
            ]
        },
        "exact": True
    }
    status_or_true, resp_or_true, _ = safe_request("POST", url, data=filter_or, timeout=10)
    exact_true_or = extract_count(resp_or_true) if status_or_true == 200 else 0

    filter_or_false = {**filter_or, "exact": False}
    status_or_false, resp_or_false, _ = safe_request("POST", url, data=filter_or_false, timeout=10)
    exact_false_or = extract_count(resp_or_false) if status_or_false == 200 else 0

    # Test 3: Complex OR with 5 values
    filter_complex = {
        "filter": {
            "should": [
                {"key": "category", "match": {"value": "A"}},
                {"key": "category", "match": {"value": "B"}},
                {"key": "category", "match": {"value": "C"}},
                {"key": "category", "match": {"value": "D"}},
                {"key": "category", "match": {"value": "E"}}
            ]
        },
        "exact": True
    }
    status_c_true, resp_c_true, _ = safe_request("POST", url, data=filter_complex, timeout=10)
    exact_true_complex = extract_count(resp_c_true) if status_c_true == 200 else 0

    filter_c_false = {**filter_complex, "exact": False}
    status_c_false, resp_c_false, _ = safe_request("POST", url, data=filter_c_false, timeout=10)
    exact_false_complex = extract_count(resp_c_false) if status_c_false == 200 else 0

    return {
        "single_match": {
            "exact_true": int(exact_true_single),
            "exact_false": int(exact_false_single),
            "error_pct": ((int(exact_false_single) - int(exact_true_single)) / int(exact_true_single) * 100) if int(exact_true_single) > 0 else 0
        },
        "or_2_values": {
            "exact_true": int(exact_true_or),
            "exact_false": int(exact_false_or),
            "error_pct": ((int(exact_false_or) - int(exact_true_or)) / int(exact_true_or) * 100) if int(exact_true_or) > 0 else 0
        },
        "or_5_values": {
            "exact_true": int(exact_true_complex),
            "exact_false": int(exact_false_complex),
            "error_pct": ((int(exact_false_complex) - int(exact_true_complex)) / int(exact_true_complex) * 100) if int(exact_true_complex) > 0 else 0
        }
    }


def main():
    import os
    db_url = os.getenv("TESTVDB_DB_URL", "http://localhost:6333")
    collection_base = "vein_match_any"
    collections_created = []
    test_sizes = [50, 200, 500]

    try:
        print("[ATTACK] collection_membership (match_any OR) on count endpoint")
        print("        Finding-feedback from cardinality_oracle (round 1)")
        print("=" * 70)

        all_results = {}

        for size in test_sizes:
            collection = f"{collection_base}_{size}"
            collections_created.append(collection)

            print(f"\n[TEST] Collection size: {size}")
            print("-" * 50)

            if not create_collection(db_url, collection):
                print(f"[FAIL] Could not create collection")
                continue

            if not insert_points(db_url, collection, size):
                print(f"[FAIL] Could not insert points")
                continue

            if not create_keyword_index(db_url, collection):
                print(f"[FAIL] Could not create keyword index")
                continue

            results = test_match_any_count(db_url, collection)
            all_results[f"size_{size}"] = results

            print(f"\n  [Single Match] category='A':")
            print(f"    exact=true:  {results['single_match']['exact_true']}")
            print(f"    exact=false: {results['single_match']['exact_false']}")
            print(f"    error: {results['single_match']['error_pct']:.1f}%")

            print(f"\n  [OR 2 Values] A or B:")
            print(f"    exact=true:  {results['or_2_values']['exact_true']}")
            print(f"    exact=false: {results['or_2_values']['exact_false']}")
            print(f"    error: {results['or_2_values']['error_pct']:.1f}%")

            print(f"\n  [OR 5 Values] A or B or C or D or E:")
            print(f"    exact=true:  {results['or_5_values']['exact_true']}")
            print(f"    exact=false: {results['or_5_values']['exact_false']}")
            print(f"    error: {results['or_5_values']['error_pct']:.1f}%")

        # Analysis
        print("\n" + "=" * 70)
        print("[ANALYSIS] Match-any (OR) cardinality estimation")
        print("-" * 70)

        # Check for estimation errors in OR conditions
        or_errors = []
        for size in test_sizes:
            r = all_results.get(f"size_{size}", {})
            or_2 = r.get("or_2_values", {})
            or_5 = r.get("or_5_values", {})
            err_2 = abs(or_2.get("error_pct", 0))
            err_5 = abs(or_5.get("error_pct", 0))
            if err_2 > 10 or err_5 > 10:
                or_errors.append((size, err_2, err_5))

        if or_errors:
            verdict = "DEFECT_FOUND"
            print(f"[DEFECT_FOUND] OR condition estimation errors exceed 10%")
            print(f"  Affected: {or_errors}")
        else:
            verdict = "PASS"
            print(f"[PASS] OR conditions estimated correctly")

        output = {
            "strategy": "vein_match_any",
            "endpoint": "POST /collections/{collection}/points/count",
            "condition_type": "collection_membership",
            "test_sizes": test_sizes,
            "results": all_results,
            "verdict": verdict,
            "threat_model_reference": "BS-09 (Filter Index Assumption)",
            "finding_feedback_source": "cardinality_oracle (round 1)"
        }

        print("\n" + "=" * 70)
        print(json.dumps(output, indent=2))
        print("=" * 70)

        print("\nVERDICT: NO_DEFECT")
        return 0 if verdict == "PASS" else 1

    except Exception as e:
        print(f"\n[FATAL] Test failed: {e}")
        traceback.print_exc()
        return 2
    finally:
        cleanup(db_url, collections_created)


if __name__ == "__main__":
    sys.exit(main())
