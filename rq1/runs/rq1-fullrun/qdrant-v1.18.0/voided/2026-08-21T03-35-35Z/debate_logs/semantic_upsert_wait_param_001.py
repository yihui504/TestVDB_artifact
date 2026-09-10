#!/usr/bin/env python3
"""
Attack: wait parameter behavior in upsert
Target: Verify wait parameter controls operation confirmation
Strategy: behavioral_contract + state_logic
"""
import os, sys, json, time, requests

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

COLLECTION = "test_upsert_wait"
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

def test_wait_parameter():
    """
    Test wait parameter behavior.
    - wait=True should return after operation completes
    - wait=False may return before operation completes (async)
    """
    setup()

    # Test 1: wait=True
    print("\n--- Test 1: wait=True (synchronous) ---")
    start = time.time()
    status, body, raw = safe_request("PUT", f"/collections/{COLLECTION}/points", json={
        "points": [{
            "id": 1,
            "vector": [0.1] * VECTOR_DIM,
            "payload": {"tag": "sync"}
        }],
        "wait": True
    })
    elapsed = time.time() - start

    print(raw)
    print(f"Request took {elapsed:.3f}s")

    if status not in (200, 201, 204):
        print(f"VERDICT: SCRIPT_ERROR — upsert with wait=True failed: {status}")
        teardown()
        sys.exit(2)

    # With wait=True, point should be immediately searchable
    status, body, raw = safe_request("POST", f"/collections/{COLLECTION}/points/search", json={
        "vector": [0.1] * VECTOR_DIM,
        "limit": 5
    })

    results = body.get("result") if isinstance(body, dict) else None
    if results and len(results) > 0:
        print("Point searchable immediately (wait=True worked)")
    else:
        print("WARNING: Point not immediately searchable despite wait=True")

    # Test 2: wait=False
    print("\n--- Test 2: wait=False (asynchronous) ---")
    start = time.time()
    status, body, raw = safe_request("PUT", f"/collections/{COLLECTION}/points", json={
        "points": [{
            "id": 2,
            "vector": [0.2] * VECTOR_DIM,
            "payload": {"tag": "async"}
        }],
        "wait": False
    })
    elapsed = time.time() - start

    print(raw)
    print(f"Request took {elapsed:.3f}s")

    if status not in (200, 201, 202, 204):
        print(f"VERDICT: SCRIPT_ERROR — upsert with wait=False failed: {status}")
        teardown()
        sys.exit(2)

    # With wait=False, might not be immediately searchable
    # But should be searchable within a short time
    time.sleep(0.5)
    status, body, raw = safe_request("POST", f"/collections/{COLLECTION}/points/search", json={
        "vector": [0.2] * VECTOR_DIM,
        "limit": 5
    })

    results = body.get("result") if isinstance(body, dict) else None
    if results and len(results) > 0:
        print("Point searchable after short delay (wait=False behavior OK)")
    else:
        print("NOTE: Point not searchable after 0.5s delay")

    # Test 3: Multiple points with wait=True
    print("\n--- Test 3: Batch with wait=True ---")
    batch = [{"id": i, "vector": [0.3] * VECTOR_DIM} for i in range(10, 15)]
    start = time.time()
    status, body, raw = safe_request("PUT", f"/collections/{COLLECTION}/points", json={
        "points": batch,
        "wait": True
    })
    elapsed = time.time() - start

    print(f"Batch of {len(batch)} points took {elapsed:.3f}s with wait=True")

    if status not in (200, 201, 204):
        print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure)")
        print(f"Batch upsert with wait=True failed: {status}")
        teardown()
        sys.exit(1)

    # Verify all points are searchable
    status, body, raw = safe_request("POST", f"/collections/{COLLECTION}/points/search", json={
        "vector": [0.3] * VECTOR_DIM,
        "limit": 20
    })

    results = body.get("result") if isinstance(body, dict) else None
    if results:
        result_ids = [r.get("id") for r in results if isinstance(r, dict)]
        expected_ids = [10, 11, 12, 13, 14]
        found = sum(1 for eid in expected_ids if eid in result_ids)
        print(f"Found {found}/{len(expected_ids)} batch points")

        if found < len(expected_ids):
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print("Not all batch points searchable despite wait=True")
            teardown()
            sys.exit(1)

    print("\nVERDICT: NO_DEFECT")
    teardown()

if __name__ == "__main__":
    test_wait_parameter()
