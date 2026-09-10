#!/usr/bin/env python3
"""
Attack: qdrant_behavioral_upsert_then_search_001 + search correctness
Target: Upserted points should be immediately searchable (within 1 second)
Strategy: behavioral_contract + search_correctness
"""
import os, sys, time, json, requests

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

COLLECTION = "test_semantic_upsert_immediate_001"
VECTOR_DIM = 128

def setup():
    """Create test collection"""
    # Cleanup first
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

def test_upsert_immediate_search():
    """
    Behavioral contract: Upserted points should be immediately searchable.
    Contract qdrant_behavioral_upsert_then_search_001 states upserted points should be searchable.
    """
    setup()

    # Upsert point
    upsert_status, upsert_body, upsert_raw = safe_request("PUT", f"/collections/{COLLECTION}/points", json={
        "points": [
            {
                "id": 1,
                "vector": [0.1] * VECTOR_DIM,
                "payload": {"category": "test"}
            }
        ]
    })

    if upsert_status not in (200, 201, 204):
        print(f"VERDICT: SCRIPT_ERROR — upsert failed: {upsert_status}")
        print(upsert_raw)
        teardown()
        sys.exit(2)

    # Wait minimal time (1 second) - should be searchable per contract
    time.sleep(1)

    # Search immediately
    search_status, search_body, search_raw = safe_request("POST", f"/collections/{COLLECTION}/points/search", json={
        "vector": [0.1] * VECTOR_DIM,
        "limit": 5,
        "with_payload": True
    })

    print(search_raw)

    # Extract results from Qdrant response (body.get("result"))
    results = search_body.get("result") if isinstance(search_body, dict) else None

    if results is None or not hasattr(results, '__len__') or len(results) == 0:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print("Expected upserted point to be searchable within 1 second")
        print(f"Search returned: {results}")
        teardown()
        sys.exit(1)

    # Verify the upserted point is in results
    found = False
    for r in results:
        if isinstance(r, dict) and r.get("id") == 1:
            found = True
            break

    if not found:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print(f"Expected point id=1 in search results, got: {[r.get('id') if isinstance(r, dict) else r for r in results]}")
        teardown()
        sys.exit(1)

    print("VERDICT: NO_DEFECT")
    teardown()

if __name__ == "__main__":
    test_upsert_immediate_search()
