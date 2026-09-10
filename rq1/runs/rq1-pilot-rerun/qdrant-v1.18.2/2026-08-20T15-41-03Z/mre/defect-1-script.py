#!/usr/bin/env python3
"""MRE for TESTVDB-QDRANT-1: Filter has_id Edge Cases"""
import os, sys, json, requests, time

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_URL = os.environ.get("TESTVDB_DB_URL", "http://localhost:6333")
HEADERS = {"Content-Type": "application/json"}

COLLECTION_NAME = "testvdb_defect1_mre"
POINT_ID = 100

def safe_request(method, path, **kwargs):
    try:
        resp = requests.request(method, f"{DB_URL}{path}", timeout=10, headers=HEADERS, **kwargs)
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        return resp.status_code, body
    except Exception as e:
        return 0, str(e)

def setup():
    print("[SETUP] Creating test collection...")
    safe_request("DELETE", f"/collections/{COLLECTION_NAME}")
    time.sleep(0.2)

    create_payload = {
        "vectors": {"size": 4, "distance": "Cosine"}
    }
    status, body = safe_request("PUT", f"/collections/{COLLECTION_NAME}", json=create_payload)
    if status != 200:
        print(f"FAIL: Collection creation failed: {status} {body}")
        return False

    time.sleep(0.5)

    point_payload = {
        "points": [
            {"id": POINT_ID, "vector": [0.1, 0.2, 0.3, 0.4]}
        ]
    }
    status, body = safe_request("PUT", f"/collections/{COLLECTION_NAME}/points", json=point_payload)
    if status != 200:
        print(f"FAIL: Point creation failed: {status} {body}")
        return False

    print(f"OK: Collection '{COLLECTION_NAME}' ready with point {POINT_ID}")
    return True

def test_has_id_empty_list():
    print("\n[TEST 1] has_id with empty list []")
    payload = {
        "vector": [0.1, 0.2, 0.3, 0.4],
        "limit": 10,
        "filter": {"must": [{"has_id": []}]}
    }
    status, body = safe_request("POST", f"/collections/{COLLECTION_NAME}/points/query", json=payload)
    count = len(body.get("result", [])) if isinstance(body, dict) else 0
    print(f"  has_id=[]: status={status}, count={count}")

    if status == 200 and count == 1:
        print("  DEFECT_CANDIDATE: Empty has_id should return 0, got 1")
        return True
    return False

def test_has_id_nonexistent_ids():
    print("\n[TEST 2] has_id with ONLY non-existent IDs [999, 998, 997]")
    payload = {
        "vector": [0.1, 0.2, 0.3, 0.4],
        "limit": 10,
        "filter": {"must": [{"has_id": [999, 998, 997]}]}
    }
    status, body = safe_request("POST", f"/collections/{COLLECTION_NAME}/points/query", json=payload)
    count = len(body.get("result", [])) if isinstance(body, dict) else 0
    print(f"  has_id=[999,998,997]: status={status}, count={count}")

    if status == 200 and count == 1:
        print("  DEFECT_CANDIDATE: Non-existent IDs should return 0, got 1")
        return True
    return False

def reproduce():
    if not setup():
        print("\nVERDICT: NOT_REPRODUCED (setup failed)")
        return False

    defect1 = test_has_id_empty_list()
    defect2 = test_has_id_nonexistent_ids()

    print("\n============================================================")
    print("ANALYSIS COMPLETE")
    print("============================================================")

    if defect1 or defect2:
        print("VERDICT: DEFECT_REPRODUCED")
        return True
    else:
        print("VERDICT: NOT_REPRODUCED")
        return False

if __name__ == "__main__":
    sys.exit(1 if reproduce() else 0)
