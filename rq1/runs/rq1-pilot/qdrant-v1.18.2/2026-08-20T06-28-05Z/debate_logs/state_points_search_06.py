#!/usr/bin/env python3
"""
Attack: count_consistency
Test: Upsert idempotence — verify duplicate upserts handled correctly
Endpoint: points+search
Constraint: qdrant_state_upsert_points_001, qdrant_behavioral_upsert_points_001
Source: https://api.qdrant.tech/api-reference/points/search-points
Doc Version: 1.19.x
"""

import os
import sys
import time
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

COLL = "state_search_06"
VECTOR_DIM = 128
NUM_POINTS = 20

def safe_request(method, endpoint, json=None, timeout=10):
    """Safe HTTP request wrapper with unified error handling."""
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.request(method, url, json=json, headers=headers, timeout=timeout)
        status_code = response.status_code
        raw_text = response.text
        try:
            body = response.json()
        except:
            body = raw_text
        return status_code, body, raw_text
    except Exception as e:
        return -1, str(e), str(e)

def setup_collection():
    """Create test collection"""
    create_body = {
        "vectors": {
            "size": VECTOR_DIM,
            "distance": "Cosine"
        }
    }
    status, body, raw = safe_request("PUT", f"/collections/{COLL}", json=create_body)
    print(f"Create collection: status={status}")
    return status == 200

def upsert_points(points):
    """Upsert points"""
    status, body, raw = safe_request("PUT", f"/collections/{COLL}/points", json={"points": points})
    print(f"Upsert {len(points)} points: status={status}")
    return status == 200

def search_and_count():
    """Search and return count"""
    query_vector = [0.1] * VECTOR_DIM
    search_body = {
        "vector": query_vector,
        "limit": 10000,
        "with_payload": True
    }

    status, body, raw = safe_request("POST", f"/collections/{COLL}/points/search", json=search_body)
    if status != 200:
        return None, f"search failed with status {status}"

    try:
        results = body.get("result", [])
        return len(results), "ok"
    except Exception as e:
        return None, f"parse error: {e}"

def main():
    # Cleanup existing
    try:
        safe_request("DELETE", f"/collections/{COLL}")
    except:
        pass

    if not setup_collection():
        print("VERDICT: SCRIPT_ERROR — Failed to create collection")
        sys.exit(2)

    time.sleep(0.5)

    # Create initial points
    points = []
    for i in range(NUM_POINTS):
        points.append({
            "id": i,
            "vector": [0.1] * VECTOR_DIM,
            "payload": {"version": 1, "idx": i}
        })

    if not upsert_points(points):
        print("VERDICT: SCRIPT_ERROR — Failed to upsert initial points")
        try:
            safe_request("DELETE", f"/collections/{COLL}")
        except:
            pass
        sys.exit(2)

    time.sleep(1)

    # Verify initial count
    count, msg = search_and_count()
    if count is None:
        print(f"VERDICT: SCRIPT_ERROR — Initial search failed: {msg}")
        try:
            safe_request("DELETE", f"/collections/{COLL}")
        except:
            pass
        sys.exit(2)

    if count != NUM_POINTS:
        print(f"VERDICT: SCRIPT_ERROR — Initial count mismatch: expected {NUM_POINTS}, got {count}")
        try:
            safe_request("DELETE", f"/collections/{COLL}")
        except:
            pass
        sys.exit(2)

    print(f"Initial count verified: {count}")

    # Upsert same IDs again with updated payload (idempotence test)
    updated_points = []
    for i in range(NUM_POINTS):
        updated_points.append({
            "id": i,
            "vector": [0.1] * VECTOR_DIM,
            "payload": {"version": 2, "idx": i}
        })

    if not upsert_points(updated_points):
        print("VERDICT: SCRIPT_ERROR — Failed to upsert updated points")
        try:
            safe_request("DELETE", f"/collections/{COLL}")
        except:
            pass
        sys.exit(2)

    time.sleep(1)

    # Verify count unchanged (should still be NUM_POINTS, not 2*NUM_POINTS)
    final_count, msg = search_and_count()
    if final_count is None:
        print(f"VERDICT: SCRIPT_ERROR — Final search failed: {msg}")
        try:
            safe_request("DELETE", f"/collections/{COLL}")
        except:
            pass
        sys.exit(2)

    if final_count != NUM_POINTS:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Idempotence violation: expected {NUM_POINTS}, got {final_count}")
        try:
            safe_request("DELETE", f"/collections/{COLL}")
        except:
            pass
        sys.exit(1)

    # Verify data was updated (last write wins)
    query_vector = [0.1] * VECTOR_DIM
    search_body = {
        "vector": query_vector,
        "limit": 10000,
        "with_payload": True
    }

    status, body, raw = safe_request("POST", f"/collections/{COLL}/points/search", json=search_body)
    if status != 200:
        print(f"VERDICT: SCRIPT_ERROR — Verification search failed: status {status}")
        try:
            safe_request("DELETE", f"/collections/{COLL}")
        except:
            pass
        sys.exit(2)

    try:
        results = body.get("result", [])
        version_mismatch = 0
        for r in results:
            payload = r.get("payload", {})
            if payload.get("version") != 2:
                version_mismatch += 1

        if version_mismatch > 0:
            print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — {version_mismatch} points not updated to version 2")
            try:
                safe_request("DELETE", f"/collections/{COLL}")
            except:
                pass
            sys.exit(1)

    except Exception as e:
        print(f"VERDICT: SCRIPT_ERROR — Failed to verify payloads: {e}")
        try:
            safe_request("DELETE", f"/collections/{COLL}")
        except:
            pass
        sys.exit(2)

    print("VERDICT: NO_DEFECT")

    # Cleanup
    try:
        safe_request("DELETE", f"/collections/{COLL}")
    except Exception:
        pass

if __name__ == "__main__":
    main()
