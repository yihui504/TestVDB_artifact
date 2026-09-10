#!/usr/bin/env python3
"""
Attack: state_consistency | create_persistence | eventual_consistency
Strategy: 1 (CRUD后COUNT一致性 - 适配CREATE后持久性测试)
Endpoint: collections+create
Constraint IDs:
  - behavioral_contracts::qdrant_behavioral_create_visibility_001
  - state_invariants::qdrant_invariant_create_query_001
Source URL: https://api.qdrant.tech/api-reference/collections/create-collection
Doc Version: 1.19.x
Expected Defect Type: Type4_StateLogicViolation
Blindspot: BS-03 (Concurrency Blindness) - state persistence timing
"""

import os
import sys
import time
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

def safe_request(method, endpoint, json=None, timeout=10):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text)
    """
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

COLL_NAME = "test_state_create_persistence"
create_body = {
    "vectors": {
        "size": 128,
        "distance": "Cosine"
    },
    "hnsw_config": {
        "m": 16,
        "ef_construct": 100
    }
}

# Cleanup: try delete existing collection
try:
    safe_request("DELETE", f"/collections/{COLL_NAME}")
    time.sleep(0.2)
except Exception:
    pass

# Create collection
status_c, body_c, raw_c = safe_request("PUT", f"/collections/{COLL_NAME}", json=create_body)
print(f"Create status: {status_c}")
print(f"Create raw: {raw_c}")

if status_c != 200:
    print(f"VERDICT: SCRIPT_ERROR — Create failed with status {status_c}")
    sys.exit(2)

# Test immediate visibility (0ms delay)
status_imm, body_imm, raw_imm = safe_request("GET", f"/collections/{COLL_NAME}")
print(f"Immediate get status: {status_imm}")

if status_imm != 200:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Collection not immediately visible (status {status_imm})")
    sys.exit(1)

# Test visibility after short delays
delays = [0.01, 0.05, 0.1, 0.2]
for delay in delays:
    time.sleep(delay)
    status, body, raw = safe_request("GET", f"/collections/{COLL_NAME}")
    if status != 200:
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Collection disappeared after {delay}s delay")
        sys.exit(1)

print(f"Collection visible at all delays: {delays}")

# Test: List collections visibility
status_list, body_list, raw_list = safe_request("GET", "/collections")
print(f"List collections status: {status_list}")

if status_list != 200:
    print(f"VERDICT: SCRIPT_ERROR — List failed with status {status_list}")
    sys.exit(2)

try:
    collections = body_list.get("result", {}).get("collections", [])
    collection_names = [c.get("name") for c in collections if isinstance(c, dict)]
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR — Failed to parse list: {e}")
    sys.exit(2)

print(f"Collections in list: {len(collection_names)} items")

if COLL_NAME not in collection_names:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Collection not in list")
    sys.exit(1)

# Verify configuration persistence
status_conf, body_conf, raw_conf = safe_request("GET", f"/collections/{COLL_NAME}")
print(f"Get config status: {status_conf}")

try:
    result = body_conf.get("result", {})
    vectors_config = result.get("config", {}).get("params", {}).get("vectors", {})

    vector_size = vectors_config.get("size")
    distance = vectors_config.get("distance")

    print(f"Persisted config: size={vector_size}, distance={distance}")

    if vector_size != 128 or distance != "Cosine":
        print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Configuration mismatch: expected size=128, distance=Cosine")
        sys.exit(1)

except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR — Failed to parse config: {e}")
    sys.exit(2)

print(f"VERDICT: NO_DEFECT — Collection state persists correctly")

# Cleanup
try:
    safe_request("DELETE", f"/collections/{COLL_NAME}")
except Exception:
    pass

sys.exit(0)
