"""
Attack: with_payload and with_vector parameter semantics
Strategy: behavioral_contract + type_coercion
Endpoint: points+search
Constraint: qdrant_type_search_points_001 (vector dimension match)
Target: qdrant v1.18.2

Tests with_payload and with_vector parameters:
1. Type coercion (string/int/boolean confusion)
2. Behavioral correctness: when with_payload=true, payload should be returned
3. Behavioral correctness: when with_vector=true, vectors should be returned
4. Invalid payload selector format

Blindspot: BS-02 (Error Message Negligence), BS-05 (Documentation Drift)
"""

import os, sys, json, time
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

COLLECTION = "test_search_with_params"
VECTOR_DIM = 128
VECTOR_KEY = "vector"
POINT_WRAP = "points"

def safe_request(method, path, json=None, params=None):
    """Safe request wrapper avoiding bare JSON chains"""
    url = f"{BASE_URL}/{path}"
    try:
        resp = requests.request(method, url, json=json, params=params, timeout=30)
        return resp.status_code, resp.json() if resp.text else None, resp.text
    except Exception as e:
        return 0, None, str(e)

def setup_collection():
    """Create test collection"""
    status, body, raw = safe_request("PUT", "collections/" + COLLECTION, json={
        "vectors": {
            "size": VECTOR_DIM,
            "distance": "Cosine"
        }
    })
    if status not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — collection setup failed: {status}")
        sys.exit(2)

def teardown():
    """Cleanup with try/except per规范"""
    try:
        safe_request("DELETE", f"collections/{COLLECTION}")
    except:
        pass

def main():
    setup_collection()
    time.sleep(0.5)

    # Insert test points with payload
    test_points = [
        {"id": 1, VECTOR_KEY: [0.1]*VECTOR_DIM, "payload": {"category": "A", "score": 10}},
        {"id": 2, VECTOR_KEY: [0.2]*VECTOR_DIM, "payload": {"category": "B", "score": 20}},
    ]
    for pt in test_points:
        status, _, raw = safe_request("PUT", f"collections/{COLLECTION}/points", json={POINT_WRAP: [pt]})
        if status not in (200, 201, 204):
            print(f"VERDICT: SCRIPT_ERROR — insert failed: {status}")
            teardown()
            sys.exit(2)

    time.sleep(0.5)

    defects = []

    # Test 1: Type coercion - string "true" instead of boolean for with_payload
    status, body, raw = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
        VECTOR_KEY: [0.1]*VECTOR_DIM,
        "limit": 10,
        "with_payload": "true"
    })
    if status == 200:
        defects.append(f"DEFECT_FOUND (Type1_IllegalSuccess) — String 'true' accepted as with_payload boolean")
    else:
        print(f"INFO: String 'true' for with_payload rejected (status {status})")

    # Test 2: Type coercion - integer 1 instead of boolean for with_vector
    status, body, raw = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
        VECTOR_KEY: [0.1]*VECTOR_DIM,
        "limit": 10,
        "with_vector": 1
    })
    if status == 200:
        defects.append(f"DEFECT_FOUND (Type1_IllegalSuccess) — Integer 1 accepted as with_vector boolean")
    else:
        print(f"INFO: Integer 1 for with_vector rejected (status {status})")

    # Test 3: Behavioral correctness - with_payload=true should return payload
    status, body, raw = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
        VECTOR_KEY: [0.1]*VECTOR_DIM,
        "limit": 10,
        "with_payload": True
    })
    if status == 200:
        if body and "result" in body and len(body["result"]) > 0:
            first_result = body["result"][0]
            if "payload" not in first_result:
                defects.append(f"DEFECT_FOUND (Type4_StateLogicViolation) — with_payload=true but payload not in result")
            else:
                print(f"INFO: with_payload=true correctly returns payload")
        else:
            defects.append(f"DEFECT_FOUND (Type4_StateLogicViolation) — with_payload=true search returned no results")
    else:
        defects.append(f"DEFECT_FOUND (Type3_RuntimeFailure) — with_payload=true search failed")

    # Test 4: Behavioral correctness - with_vector=true should return vectors
    status, body, raw = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
        VECTOR_KEY: [0.1]*VECTOR_DIM,
        "limit": 10,
        "with_vector": True
    })
    if status == 200:
        if body and "result" in body and len(body["result"]) > 0:
            first_result = body["result"][0]
            if "vector" not in first_result:
                defects.append(f"DEFECT_FOUND (Type4_StateLogicViolation) — with_vector=true but vector not in result")
            else:
                print(f"INFO: with_vector=true correctly returns vector")
        else:
            defects.append(f"DEFECT_FOUND (Type4_StateLogicViolation) — with_vector=true search returned no results")
    else:
        defects.append(f"DEFECT_FOUND (Type3_RuntimeFailure) — with_vector=true search failed")

    # Test 5: with_payload as array (payload selector)
    status, body, raw = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
        VECTOR_KEY: [0.1]*VECTOR_DIM,
        "limit": 10,
        "with_payload": ["category", "score"]
    })
    if status == 200:
        if body and "result" in body and len(body["result"]) > 0:
            first_result = body["result"][0]
            if "payload" not in first_result:
                defects.append(f"DEFECT_FOUND (Type4_StateLogicViolation) — with_payload=[selector] but payload not in result")
            else:
                payload = first_result.get("payload", {})
                if "category" in payload and "score" in payload:
                    print(f"INFO: with_payload=[selector] correctly returns selected fields")
                elif isinstance(payload, dict) and len(payload) > 0:
                    print(f"INFO: Payload returned with keys: {list(payload.keys())}")
                else:
                    defects.append(f"DEFECT_FOUND (Type4_StateLogicViolation) — with_payload selector did not return expected fields")
        else:
            defects.append(f"DEFECT_FOUND (Type4_StateLogicViolation) — with_payload selector search returned no results")
    else:
        print(f"INFO: with_payload as array rejected (status {status})")

    # Test 6: with_payload=false should not return payload
    status, body, raw = safe_request("POST", f"collections/{COLLECTION}/points/search", json={
        VECTOR_KEY: [0.1]*VECTOR_DIM,
        "limit": 10,
        "with_payload": False
    })
    if status == 200:
        if body and "result" in body and len(body["result"]) > 0:
            first_result = body["result"][0]
            if "payload" in first_result:
                defects.append(f"DEFECT_FOUND (Type4_StateLogicViolation) — with_payload=false but payload still in result")
            else:
                print(f"INFO: with_payload=false correctly omits payload")
        else:
            defects.append(f"DEFECT_FOUND (Type4_StateLogicViolation) — with_payload=false search returned no results")
    else:
        defects.append(f"DEFECT_FOUND (Type3_RuntimeFailure) — with_payload=false search failed")

    teardown()

    if defects:
        for d in defects:
            print(d)
        print("VERDICT: DEFECT_FOUND")
        sys.exit(1)
    else:
        print("VERDICT: NO_DEFECT")
        sys.exit(0)

if __name__ == "__main__":
    main()
