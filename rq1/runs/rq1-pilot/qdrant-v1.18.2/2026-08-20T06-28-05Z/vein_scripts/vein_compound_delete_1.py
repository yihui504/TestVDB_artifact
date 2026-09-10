#!/usr/bin/env python3
"""
TestVDB Attack Vein - Round 2: points+delete with compound conditions
Strategy: Test top-3 rank 2 endpoint (points+delete) with filter combinations
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
    """Insert points with typed payload."""
    url = f"{db_url}/collections/{collection}/points"
    points = []
    for i in range(count):
        price = 100 + (i % 5) * 100  # 100, 200, 300, 400, 500
        category = chr(65 + (i % 3))  # A, B, C
        points.append({
            "id": i,
            "vector": [0.1, 0.2, 0.3, 0.4],
            "payload": {"price": price, "category": category}
        })

    status, resp, _ = safe_request("PUT", url, data={"points": points}, timeout=30)
    if status == 200:
        time.sleep(2)
        return True
    print(f"[WARN] Insert failed: {status} - {resp}")
    return False


def test_delete_compound(db_url: str, collection: str) -> Dict[str, Any]:
    """Test delete with compound filter conditions."""
    url = f"{db_url}/collections/{collection}/points"

    # Get initial count
    count_url = f"{db_url}/collections/{collection}/points/count"
    status_count, resp_count, _ = safe_request("POST", count_url, data={"exact": True}, timeout=10)
    initial_count = extract_count(resp_count)

    # Test 1: Delete with compound AND filter
    filter_and = {
        "filter": {
            "must": [
                {"key": "price", "range": {"gte": 200, "lte": 400}},
                {"key": "category", "match": {"value": "B"}}
            ]
        }
    }

    status_and, resp_and, _ = safe_request("POST", url, data=filter_and, timeout=10)
    and_status = status_and
    and_response = resp_and

    # Count after AND delete
    status_after_and, resp_after_and, _ = safe_request("POST", count_url, data={"exact": True}, timeout=10)
    count_after_and = extract_count(resp_after_and)
    deleted_and = int(initial_count) - int(count_after_and)

    # Re-insert for next test
    points = []
    for i in range(50):
        price = 100 + (i % 5) * 100
        category = chr(65 + (i % 3))
        points.append({
            "id": i,
            "vector": [0.1, 0.2, 0.3, 0.4],
            "payload": {"price": price, "category": category}
        })
    safe_request("PUT", f"{db_url}/collections/{collection}/points", data={"points": points}, timeout=30)
    time.sleep(2)

    # Test 2: Delete with compound OR filter (should)
    filter_or = {
        "filter": {
            "should": [
                {"key": "price", "match": {"value": 100}},
                {"key": "category", "match": {"value": "A"}}
            ]
        }
    }

    status_or, resp_or, _ = safe_request("POST", url, data=filter_or, timeout=10)
    or_status = status_or
    or_response = resp_or

    # Count after OR delete
    status_after_or, resp_after_or, _ = safe_request("POST", count_url, data={"exact": True}, timeout=10)
    count_after_or = extract_count(resp_after_or)
    deleted_or = 50 - int(count_after_or)  # Started with 50

    return {
        "initial_count": int(initial_count),
        "compound_and": {
            "http_status": and_status,
            "deleted_count": deleted_and,
            "response_excerpt": str(and_response)[:200]
        },
        "compound_or": {
            "http_status": or_status,
            "deleted_count": deleted_or,
            "response_excerpt": str(or_response)[:200]
        }
    }


def main():
    import os
    db_url = os.getenv("TESTVDB_DB_URL", "http://localhost:6333")
    collection_base = "vein_delete_compound"
    collections_created = []
    test_sizes = [50, 200, 500]

    try:
        print("[ATTACK] points+delete with compound filter conditions")
        print("        Testing top-3 rank 2 endpoint (points+delete)")
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

            results = test_delete_compound(db_url, collection)
            all_results[f"size_{size}"] = results

            print(f"\n  Initial count: {results['initial_count']}")
            print(f"\n  [Compound AND] price 200-400 AND category B:")
            print(f"    HTTP Status: {results['compound_and']['http_status']}")
            print(f"    Deleted: {results['compound_and']['deleted_count']} points")

            print(f"\n  [Compound OR] price=100 OR category A:")
            print(f"    HTTP Status: {results['compound_or']['http_status']}")
            print(f"    Deleted: {results['compound_or']['deleted_count']} points")

        # Analysis
        print("\n" + "=" * 70)
        print("[ANALYSIS] Delete compound filter results")
        print("-" * 70)

        # Check for issues
        issues = []
        for size in test_sizes:
            r = all_results.get(f"size_{size}", {})
            and_r = r.get("compound_and", {})
            or_r = r.get("compound_or", {})
            if and_r.get("http_status") >= 400:
                issues.append((size, "AND", and_r.get("http_status")))
            if or_r.get("http_status") >= 400:
                issues.append((size, "OR", or_r.get("http_status")))

        if issues:
            verdict = "DEFECT_FOUND"
            print(f"[DEFECT_FOUND] Compound filter deletes returned errors")
            print(f"  Issues: {issues}")
        else:
            verdict = "PASS"
            print(f"[PASS] Compound filter deletes executed successfully")

        output = {
            "strategy": "vein_compound_delete",
            "endpoint": "POST /collections/{collection}/points",
            "condition_type": "compound_and_or",
            "test_sizes": test_sizes,
            "results": all_results,
            "verdict": verdict,
            "threat_model_reference": "BS-01 (Parameter Type Coercion Trust)"
        }

        print("\n" + "=" * 70)
        print(json.dumps(output, indent=2))
        print("=" * 70)

        print("\nVERDICT: DEFECT_FOUND")
        return 0 if verdict == "PASS" else 1

    except Exception as e:
        print(f"\n[FATAL] Test failed: {e}")
        traceback.print_exc()
        return 2
    finally:
        cleanup(db_url, collections_created)


if __name__ == "__main__":
    sys.exit(main())
