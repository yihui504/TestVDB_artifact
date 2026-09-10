"""
Test: Range Constraints - HNSW Configuration
Attack: Boundary/Range Validation
Verifies that HNSW config parameters enforce range constraints per contract
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

def test_hnsw_range_constraints():
    """Verify HNSW config range constraints: m ∈ [2, 100], ef_construct ∈ [10, 1000]"""
    collection_base = "test_hnsw_ranges"

    # Test cases for m (max connections): should be in [2, 100]
    m_test_cases = [
        {"value": 1, "should_accept": False, "desc": "m=1 (below min 2)"},
        {"value": 2, "should_accept": True, "desc": "m=2 (min boundary)"},
        {"value": 50, "should_accept": True, "desc": "m=50 (mid-range)"},
        {"value": 100, "should_accept": True, "desc": "m=100 (max boundary)"},
        {"value": 101, "should_accept": False, "desc": "m=101 (above max 100)"},
        {"value": 0, "should_accept": False, "desc": "m=0 (zero)"},
        {"value": -5, "should_accept": False, "desc": "m=-5 (negative)"},
    ]

    print("=" * 60)
    print("Testing HNSW m parameter range [2, 100]")
    print("=" * 60)

    for i, test_case in enumerate(m_test_cases):
        collection_name = f"{collection_base}_m_{i}"
        m_val = test_case["value"]

        print(f"\nTest: m={m_val} - {test_case['desc']}")

        payload = {
            "vectors": {
                "size": 128,
                "distance": "Cosine"
            },
            "hnsw_config": {
                "m": m_val
            }
        }

        status, body, raw = safe_request(
            "PUT",
            f"/collections/{collection_name}",
            json_data=payload
        )

        print(f"Status: {status}")

        if test_case["should_accept"]:
            if status in (200, 201):
                print(f"✓ Correctly accepted m={m_val}")
                try:
                    safe_request("DELETE", f"/collections/{collection_name}")
                except:
                    pass
            else:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection)")
                print(f"Valid m={m_val} was rejected with status {status}")
                print(f"Contract: m should accept values in [2, 100]")
                sys.exit(1)
        else:
            if status in (200, 201):
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)")
                print(f"Invalid m={m_val} was incorrectly accepted")
                print(f"Contract: m should reject values outside [2, 100]")
                try:
                    safe_request("DELETE", f"/collections/{collection_name}")
                except:
                    pass
                sys.exit(1)
            else:
                print(f"✓ Correctly rejected m={m_val}")

    # Test cases for ef_construct: should be in [10, 1000]
    ef_test_cases = [
        {"value": 9, "should_accept": False, "desc": "ef_construct=9 (below min 10)"},
        {"value": 10, "should_accept": True, "desc": "ef_construct=10 (min boundary)"},
        {"value": 500, "should_accept": True, "desc": "ef_construct=500 (mid-range)"},
        {"value": 1000, "should_accept": True, "desc": "ef_construct=1000 (max boundary)"},
        {"value": 1001, "should_accept": False, "desc": "ef_construct=1001 (above max 1000)"},
        {"value": 0, "should_accept": False, "desc": "ef_construct=0 (zero)"},
        {"value": -100, "should_accept": False, "desc": "ef_construct=-100 (negative)"},
    ]

    print("\n" + "=" * 60)
    print("Testing HNSW ef_construct parameter range [10, 1000]")
    print("=" * 60)

    for i, test_case in enumerate(ef_test_cases):
        collection_name = f"{collection_base}_ef_{i}"
        ef_val = test_case["value"]

        print(f"\nTest: ef_construct={ef_val} - {test_case['desc']}")

        payload = {
            "vectors": {
                "size": 128,
                "distance": "Cosine"
            },
            "hnsw_config": {
                "ef_construct": ef_val
            }
        }

        status, body, raw = safe_request(
            "PUT",
            f"/collections/{collection_name}",
            json_data=payload
        )

        print(f"Status: {status}")

        if test_case["should_accept"]:
            if status in (200, 201):
                print(f"✓ Correctly accepted ef_construct={ef_val}")
                try:
                    safe_request("DELETE", f"/collections/{collection_name}")
                except:
                    pass
            else:
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection)")
                print(f"Valid ef_construct={ef_val} was rejected with status {status}")
                print(f"Contract: ef_construct should accept values in [10, 1000]")
                sys.exit(1)
        else:
            if status in (200, 201):
                print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)")
                print(f"Invalid ef_construct={ef_val} was incorrectly accepted")
                print(f"Contract: ef_construct should reject values outside [10, 1000]")
                try:
                    safe_request("DELETE", f"/collections/{collection_name}")
                except:
                    pass
                sys.exit(1)
            else:
                print(f"✓ Correctly rejected ef_construct={ef_val}")

    print("\n" + "=" * 60)
    print("VERDICT: NO_DEFECT")
    print("All HNSW range constraint tests passed")
    print("=" * 60)

if __name__ == "__main__":
    test_hnsw_range_constraints()
