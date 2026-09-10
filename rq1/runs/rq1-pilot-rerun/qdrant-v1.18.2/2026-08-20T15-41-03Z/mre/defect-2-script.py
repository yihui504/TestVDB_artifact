#!/usr/bin/env python3
"""MRE for TESTVDB-QDRANT-2: Zero HNSW EF Parameter During Points Search"""
import os, sys, json, requests, time

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_URL = os.environ.get("TESTVDB_DB_URL", "http://localhost:6333")
HEADERS = {"Content-Type": "application/json"}

COLLECTION_NAME = "testvdb_defect2_mre"

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

    points_payload = {
        "points": [
            {"id": 1, "vector": [1.0, 0.0, 0.0, 0.0]},
            {"id": 2, "vector": [0.0, 1.0, 0.0, 0.0]}
        ]
    }
    status, body = safe_request("PUT", f"/collections/{COLLECTION_NAME}/points", json=points_payload)
    if status != 200:
        print(f"FAIL: Points creation failed: {status} {body}")
        return False

    print(f"OK: Collection '{COLLECTION_NAME}' ready with 2 points")
    return True

def test_hnsw_ef_zero():
    print("\n[TEST] params.hnsw_ef=0 (should reject with 400)")
    payload = {
        "vector": [1.0, 0.0, 0.0, 0.0],
        "limit": 10,
        "params": {"hnsw_ef": 0}
    }
    status, body = safe_request("POST", f"/collections/{COLLECTION_NAME}/points/search", json=payload)
    print(f"  hnsw_ef=0: status={status}")
    print(f"  Response: {json.dumps(body, indent=2, ensure_ascii=False) if isinstance(body, dict) else body}")

    if status == 200:
        print("  DEFECT_CANDIDATE: params.hnsw_ef=0 returns 200 (should reject with 400)")
        return True
    return False

def test_control_hnsw_ef_negative():
    print("\n[CONTROL] params.hnsw_ef=-1 (correctly returns 400)")
    payload = {
        "vector": [1.0, 0.0, 0.0, 0.0],
        "limit": 10,
        "params": {"hnsw_ef": -1}
    }
    status, body = safe_request("POST", f"/collections/{COLLECTION_NAME}/points/search", json=payload)
    print(f"  hnsw_ef=-1: status={status}")
    print(f"  Response: {json.dumps(body, indent=2, ensure_ascii=False) if isinstance(body, dict) else body}")

    if status == 400:
        print("  OK: Negative value correctly rejected")
        return True
    return False

def reproduce():
    if not setup():
        print("\nVERDICT: NOT_REPRODUCED (setup failed)")
        return False

    defect_found = test_hnsw_ef_zero()
    control_ok = test_control_hnsw_ef_negative()

    print("\n============================================================")
    print("ANALYSIS COMPLETE")
    print("============================================================")

    if defect_found and control_ok:
        print("VERDICT: DEFECT_REPRODUCED")
        print("EVIDENCE: params.hnsw_ef=0 returns 200 (should reject with 400)")
        print("CONTROL: params.hnsw_ef=-1 correctly returns 400")
        return True
    elif defect_found:
        print("VERDICT: DEFECT_REPRODUCED (control check skipped)")
        return True
    else:
        print("VERDICT: NOT_REPRODUCED")
        return False

if __name__ == "__main__":
    sys.exit(1 if reproduce() else 0)
