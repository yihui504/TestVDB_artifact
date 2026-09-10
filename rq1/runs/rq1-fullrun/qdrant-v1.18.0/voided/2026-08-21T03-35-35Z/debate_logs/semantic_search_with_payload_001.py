#!/usr/bin/env python3
"""
Attack: with_payload parameter behavior
Target: Verify with_payload correctly controls payload return
Strategy: search_correctness + behavioral_contract
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

COLLECTION = "test_with_payload"
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

def test_with_payload_behavior():
    """
    Test with_payload parameter controls payload inclusion.
    - with_payload=True should include payload
    - with_payload=False should exclude payload
    - with_payload=["field"] should include only specified fields
    """
    setup()

    # Insert point with payload
    status, body, raw = safe_request("PUT", f"/collections/{COLLECTION}/points", json={
        "points": [{
            "id": 1,
            "vector": [0.1] * VECTOR_DIM,
            "payload": {
                "category": "test",
                "score": 42,
                "tags": ["a", "b"]
            }
        }]
    })
    if status not in (200, 201, 204):
        print(f"VERDICT: SCRIPT_ERROR — insert failed: {status}")
        teardown()
        sys.exit(2)

    # Test 1: with_payload=True
    print("\n--- Test 1: with_payload=True ---")
    status, body, raw = safe_request("POST", f"/collections/{COLLECTION}/points/search", json={
        "vector": [0.1] * VECTOR_DIM,
        "limit": 10,
        "with_payload": True
    })
    print(raw)

    if status != 200:
        print(f"VERDICT: SCRIPT_ERROR — search with_payload=True failed: {status}")
        teardown()
        sys.exit(2)

    results = body.get("result") if isinstance(body, dict) else None
    if results and len(results) > 0:
        first = results[0]
        if isinstance(first, dict):
            payload = first.get("payload")
            if payload is None:
                print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
                print("with_payload=True should include payload but got None")
                teardown()
                sys.exit(1)
            print(f"Payload present: {payload}")

    # Test 2: with_payload=False
    print("\n--- Test 2: with_payload=False ---")
    status, body, raw = safe_request("POST", f"/collections/{COLLECTION}/points/search", json={
        "vector": [0.1] * VECTOR_DIM,
        "limit": 10,
        "with_payload": False
    })
    print(raw)

    if status != 200:
        print(f"VERDICT: SCRIPT_ERROR — search with_payload=False failed: {status}")
        teardown()
        sys.exit(2)

    results = body.get("result") if isinstance(body, dict) else None
    if results and len(results) > 0:
        first = results[0]
        if isinstance(first, dict):
            payload = first.get("payload")
            if payload is not None:
                print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
                print(f"with_payload=False should exclude payload but got: {payload}")
                teardown()
                sys.exit(1)
            print("Payload correctly excluded")

    # Test 3: with_payload=["category"]
    print("\n--- Test 3: with_payload=['category'] (selective fields) ---")
    status, body, raw = safe_request("POST", f"/collections/{COLLECTION}/points/search", json={
        "vector": [0.1] * VECTOR_DIM,
        "limit": 10,
        "with_payload": ["category"]
    })
    print(raw)

    if status != 200:
        print(f"VERDICT: SCRIPT_ERROR — search with_payload=['category'] failed: {status}")
        teardown()
        sys.exit(2)

    results = body.get("result") if isinstance(body, dict) else None
    if results and len(results) > 0:
        first = results[0]
        if isinstance(first, dict):
            payload = first.get("payload")
            if payload is None:
                print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
                print("with_payload=['category'] should include payload but got None")
                teardown()
                sys.exit(1)
            if isinstance(payload, dict):
                has_category = "category" in payload
                has_score = "score" in payload
                print(f"Payload fields: category={has_category}, score={has_score}")

                if not has_category:
                    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
                    print("with_payload=['category'] should include 'category' field")
                    teardown()
                    sys.exit(1)

                if has_score:
                    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
                    print("with_payload=['category'] should exclude 'score' field")
                    teardown()
                    sys.exit(1)

    print("\nVERDICT: NO_DEFECT")
    teardown()

if __name__ == "__main__":
    test_with_payload_behavior()
