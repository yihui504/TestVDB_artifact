#!/usr/bin/env python3
"""
Attack: Point ID type constraints and semantics
Target: Verify point ID handling (integer vs string)
Strategy: type_coercion + behavioral_contract
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

COLLECTION = "test_upsert_id_types"
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

def test_point_id_types():
    """
    Test point ID type handling.
    Contract states ID can be integer or string.
    Should handle both, not coerce unexpectedly.
    """
    setup()

    # Test 1: Integer ID
    print("\n--- Test 1: Integer ID ---")
    status, body, raw = safe_request("PUT", f"/collections/{COLLECTION}/points", json={
        "points": [{
            "id": 1,
            "vector": [0.1] * VECTOR_DIM
        }]
    })
    print(raw)

    if status not in (200, 201, 204):
        print(f"VERDICT: SCRIPT_ERROR — integer ID insert failed: {status}")
        teardown()
        sys.exit(2)

    # Test 2: String ID
    print("\n--- Test 2: String ID ---")
    status, body, raw = safe_request("PUT", f"/collections/{COLLECTION}/points", json={
        "points": [{
            "id": "string_id_1",
            "vector": [0.2] * VECTOR_DIM
        }]
    })
    print(raw)

    if status in (400, 422):
        print("VERDICT: NO_DEFECT — string ID correctly rejected (qdrant accepts unsigned int/UUID only)")
        teardown()
        sys.exit(0)
    if status not in (200, 201, 204):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — string ID accepted: {status}")
        teardown()
        sys.exit(1)

    # Test 3: Mixed types in same batch
    print("\n--- Test 3: Mixed ID types in batch ---")
    status, body, raw = safe_request("PUT", f"/collections/{COLLECTION}/points", json={
        "points": [
            {"id": 2, "vector": [0.3] * VECTOR_DIM},
            {"id": "string_id_2", "vector": [0.4] * VECTOR_DIM},
        ]
    })
    print(raw)

    if status not in (200, 201, 204):
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalRejection)")
        print(f"Mixed ID types should be accepted but got status {status}")
        teardown()
        sys.exit(1)

    # Test 4: Verify both types are searchable
    print("\n--- Test 4: Search returns both ID types ---")
    status, body, raw = safe_request("POST", f"/collections/{COLLECTION}/points/search", json={
        "vector": [0.1] * VECTOR_DIM,
        "limit": 10
    })
    print(raw)

    if status != 200:
        print(f"VERDICT: SCRIPT_ERROR — search failed: {status}")
        teardown()
        sys.exit(2)

    results = body.get("result") if isinstance(body, dict) else None
    if results and hasattr(results, '__len__'):
        ids = [r.get("id") for r in results if isinstance(r, dict)]
        print(f"Found IDs: {ids}")

        has_int = any(isinstance(i, int) for i in ids)
        has_str = any(isinstance(i, str) for i in ids)

        if not (has_int and has_str):
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print(f"Expected both int and string IDs, got: {ids}")
            teardown()
            sys.exit(1)

    # Test 5: Boolean ID (should reject)
    print("\n--- Test 5: Boolean ID (should reject) ---")
    status, body, raw = safe_request("PUT", f"/collections/{COLLECTION}/points", json={
        "points": [{
            "id": True,
            "vector": [0.5] * VECTOR_DIM
        }]
    })
    print(raw)

    if status == 200:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)")
        print("Boolean ID should be rejected but was accepted")
        teardown()
        sys.exit(1)

    print("\nVERDICT: NO_DEFECT")
    teardown()

if __name__ == "__main__":
    test_point_id_types()
