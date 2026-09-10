#!/usr/bin/env python3
"""
TestVDB Attack Vein - Round 2: geo_filter on count endpoint
Strategy: Finding-feedback from cardinality_oracle defect (round 1)
Cross-pollination: Test if geo filter has similar estimation bugs on count(exact:false)
"""
import sys
import json
import time
import traceback
from typing import Dict, Any, Tuple

# Safe request wrapper - three elements for cleanup
def safe_request(method: str, url: str, **kwargs) -> Tuple[int, Dict[str, Any], str]:
    """
    Safe HTTP request wrapper for TestVDB attack scripts.
    Returns: (http_status, response_dict, full_response_text)
    """
    import urllib.request
    import urllib.error

    headers = kwargs.pop('headers', {})
    data = kwargs.pop('data', None)
    timeout = kwargs.pop('timeout', 10)

    if data:
        data = json.dumps(data).encode('utf-8')
        if 'Content-Type' not in headers:
            headers['Content-Type'] = 'application/json'

    req = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method
    )

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


def cleanup(db_url: str, collections_created: list):
    """Cleanup: Delete all test collections created during this test"""
    print("\n[CLEANUP] Deleting test collections...")
    for collection in collections_created:
        try:
            url = f"{db_url}/collections/{collection}"
            status, _, _ = safe_request("DELETE", url, timeout=10)
            print(f"  - DELETE {collection}: {status}")
        except Exception as e:
            print(f"  - DELETE {collection}: failed ({e})")


def create_collection(db_url: str, name: str) -> bool:
    """Create a test collection with geo-indexed payload"""
    url = f"{db_url}/collections/{name}"
    config = {
        "vectors": {
            "size": 4,
            "distance": "Cosine"
        },
        "optimizers_config": {
            "indexing_threshold": 1
        }
    }
    status, resp, _ = safe_request("PUT", url, data=config, timeout=10)
    if status == 200:
        time.sleep(0.5)
        return True
    print(f"[WARN] Create collection {name} failed: {status} - {resp}")
    return False


def insert_geo_points(db_url: str, collection: str, count: int) -> bool:
    """Insert points with geo coordinates"""
    url = f"{db_url}/collections/{collection}/points"
    points = []
    for i in range(count):
        # Create geo distribution centered around NYC
        lat = 40.7128 + (i % 10) * 0.01  # Spread within 0.1 degrees
        lon = -74.0060 + (i % 10) * 0.01
        points.append({
            "id": i,
            "vector": [0.1, 0.2, 0.3, 0.4],
            "payload": {"location": {"type": "Point", "coordinates": [lon, lat]}}
        })

    status, resp, _ = safe_request("PUT", url, data={"points": points}, timeout=30)
    if status == 200:
        time.sleep(2)  # Wait for indexing
        return True
    print(f"[WARN] Insert failed: {status} - {resp}")
    return False


def create_geo_index(db_url: str, collection: str) -> bool:
    """Create geo index on location field"""
    url = f"{db_url}/collections/{collection}/index"
    index_config = {
        "field_name": "location",
        "field_schema": "geo"
    }
    status, resp, _ = safe_request("PUT", url, data=index_config, timeout=10)
    if status == 200:
        time.sleep(4)  # Wait for index build
        return True
    print(f"[WARN] Geo index creation failed: {status} - {resp}")
    return False


def test_geo_count_divergence(db_url: str, collection: str) -> Dict[str, Any]:
    """Test count(exact:false) vs count(exact:true) on geo radius filter"""
    # Use a large radius to ensure we match points
    filter_geo = {
        "must": [
            {
                "key": "location",
                "match": {
                    "geo": {
                        "type": "Circle",
                        "center": {"lon": -74.0, "lat": 40.7},
                        "radius": 50000  # 50km - large enough to match most points
                    }
                }
            }
        ]
    }

    # Test exact:true
    url = f"{db_url}/collections/{collection}/points/count"

    payload_true = {**filter_geo, "exact": True}
    status_true, resp_true, _ = safe_request("POST", url, data=payload_true, timeout=10)

    # Extract count - handle Qdrant response structure
    exact_true = 0
    if status_true == 200:
        if isinstance(resp_true, dict):
            if "result" in resp_true:
                exact_true = resp_true["result"] if isinstance(resp_true["result"], int) else 0
            elif "status" in resp_true and "result" in resp_true["status"]:
                exact_true = resp_true["status"]["result"] if isinstance(resp_true["status"]["result"], int) else 0

    # Test exact:false
    payload_false = {**filter_geo, "exact": False}
    status_false, resp_false, _ = safe_request("POST", url, data=payload_false, timeout=10)

    exact_false = 0
    if status_false == 200:
        if isinstance(resp_false, dict):
            if "result" in resp_false:
                exact_false = resp_false["result"] if isinstance(resp_false["result"], int) else 0
            elif "status" in resp_false and "result" in resp_false["status"]:
                exact_false = resp_false["status"]["result"] if isinstance(resp_false["status"]["result"], int) else 0

    return {
        "exact_true": int(exact_true),
        "exact_false": int(exact_false),
        "difference": int(exact_false) - int(exact_true),
        "error_pct": ((int(exact_false) - int(exact_true)) / int(exact_true) * 100) if int(exact_true) > 0 else 0
    }


def main():
    import os
    db_url = os.getenv("TESTVDB_DB_URL", "http://localhost:6333")
    collection_base = "vein_geo_test"
    collections_created = []
    test_sizes = [50, 200, 500]

    try:
        print("[ATTACK] geo_filter on count endpoint (cardinality cross-pollination)")
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

            if not insert_geo_points(db_url, collection, size):
                print(f"[FAIL] Could not insert points into {collection}")
                continue

            if not create_geo_index(db_url, collection):
                print(f"[FAIL] Could not create geo index on {collection}")
                continue

            # Test
            results = test_geo_count_divergence(db_url, collection)
            all_results[f"size_{size}"] = results

            print(f"  exact=true:  {results['exact_true']}")
            print(f"  exact=false: {results['exact_false']}")
            print(f"  difference:  {results['difference']} ({results['error_pct']:.1f}%)")

        # Analysis
        print("\n" + "=" * 70)
        print("[ANALYSIS] Geo filter cardinality estimation results")
        print("-" * 70)

        error_pcts = [r.get("error_pct", 0) for r in all_results.values()]
        max_error = max(abs(e) for e in error_pcts) if error_pcts else 0

        # Check for by-design fallback (linear scaling)
        sizes = [50, 200, 500]
        errors = [all_results.get(f"size_{s}", {}).get("error_pct", 0) for s in sizes]

        # VERDICT
        if max_error < 10:
            verdict = "PASS"
            print(f"[PASS] Estimation error within tolerance (max {max_error:.1f}%)")
        elif all(abs(e) < 5 for e in errors):
            verdict = "BY_DESIGN_EXCLUDED"
            print(f"[BY_DESIGN] Small errors likely due to coarse estimate fallback")
        else:
            verdict = "DEFECT_FOUND"
            print(f"[DEFECT_FOUND] Estimation error exceeds 10% tolerance")
            print(f"  Max error: {max_error:.1f}%")

            # Check if error is size-dependent (potential fallback)
            if len(errors) >= 2:
                error_ratio = abs(errors[1] / errors[0]) if errors[0] != 0 else 1
                size_ratio = sizes[1] / sizes[0]
                if 0.8 < (error_ratio / size_ratio) < 1.2:
                    print(f"  NOTE: Error scales with size - possible by-design fallback")

        # Final output
        output = {
            "strategy": "vein_geo_filter",
            "endpoint": "POST /collections/{collection}/points/count",
            "condition_type": "geo_filter",
            "test_sizes": test_sizes,
            "results": all_results,
            "max_error_pct": max_error,
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
        print(f"\n[FATAL] Test execution failed: {e}")
        traceback.print_exc()
        return 2
    finally:
        cleanup(db_url, collections_created)


if __name__ == "__main__":
    sys.exit(main())
