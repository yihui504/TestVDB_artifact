"""
Attack: upsert_idempotence (策略 3)

Tests that upserting the same point twice increases count by 1 (not 2).
"""
import os
import sys
import time

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

import requests

def safe_request(method, endpoint, json=None, timeout=10):
    """Safe HTTP request wrapper with unified error handling."""
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.request(
            method=method,
            url=url,
            json=json,
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

COLL_NAME = "state_idempotence_test"

# Cleanup
try:
    safe_request("DELETE", f"/collections/{COLL_NAME}")
except Exception:
    pass

# Create collection
create_body = {
    "vectors": {
        "size": 128,
        "distance": "Cosine"
    }
}
status, _, raw = safe_request("PUT", f"/collections/{COLL_NAME}", json=create_body)
print(f"Create collection: {status}")
if status not in [200, 201]:
    print(raw)
    print("VERDICT: SCRIPT_ERROR — Failed to create collection")
    sys.exit(2)

# Initial count
status, body, raw = safe_request("POST", f"/collections/{COLL_NAME}/points/count", json={})
print(f"Count before: {raw}")
if status != 200:
    print("VERDICT: SCRIPT_ERROR — Count endpoint failed")
    sys.exit(2)

count_before = body.get("result", 0) if isinstance(body, dict) else 0
print(f"count_before = {count_before}")

# Upsert same point twice
point_id = 42
point = {
    "points": [
        {
            "id": point_id,
            "vector": [0.1] * 128,
            "payload": {"round": 1}
        }
    ]
}

# First upsert
status, _, raw = safe_request("PUT", f"/collections/{COLL_NAME}/points", json=point)
print(f"First upsert: {status}")
if status not in [200, 201]:
    print(f"First upsert failed: {raw}")
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — First upsert failed")
    sys.exit(1)

time.sleep(0.5)

# Count after first upsert
status, body, raw = safe_request("POST", f"/collections/{COLL_NAME}/points/count", json={})
print(f"Count after first: {raw}")
if status != 200:
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Count failed after first upsert")
    sys.exit(1)

count_after_first = body.get("result", 0) if isinstance(body, dict) else 0
print(f"count_after_first = {count_after_first}")

# Second upsert (same ID, different payload)
point["points"][0]["payload"] = {"round": 2}
status, _, raw = safe_request("PUT", f"/collections/{COLL_NAME}/points", json=point)
print(f"Second upsert: {status}")
if status not in [200, 201]:
    print(f"Second upsert failed: {raw}")
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Second upsert failed")
    sys.exit(1)

time.sleep(0.5)

# Count after second upsert
status, body, raw = safe_request("POST", f"/collections/{COLL_NAME}/points/count", json={})
print(f"Count after second: {raw}")
if status != 200:
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Count failed after second upsert")
    sys.exit(1)

count_after_second = body.get("result", 0) if isinstance(body, dict) else 0
print(f"count_after_second = {count_after_second}")

# Verify idempotence: count should increase by 1 (not 2)
expected = count_before + 1
if count_after_second != expected:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Upsert not idempotent. Expected {expected}, got {count_after_second}")
    sys.exit(1)

# Verify data correctness (last write wins)
# Get the point
status, body, raw = safe_request("GET", f"/collections/{COLL_NAME}/points/{point_id}")
print(f"Get point: {status}")
if status != 200:
    print(f"Get point failed: {raw}")
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — Get point failed")
    sys.exit(1)

retrieved = body.get("result", {}) if isinstance(body, dict) else {}
if isinstance(retrieved, list) and len(retrieved) > 0:
    retrieved = retrieved[0]

payload = retrieved.get("payload", {}) if isinstance(retrieved, dict) else {}
print(f"Retrieved payload: {payload}")

# Verify last write persisted
if payload.get("round") != 2:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Last write did not persist. Expected round=2, got {payload}")
    sys.exit(1)

# Cleanup
try:
    safe_request("DELETE", f"/collections/{COLL_NAME}")
except Exception:
    pass

print("VERDICT: NO_DEFECT")
