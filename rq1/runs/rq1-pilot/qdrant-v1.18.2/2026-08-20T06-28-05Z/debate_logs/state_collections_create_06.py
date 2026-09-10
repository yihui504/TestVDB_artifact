#!/usr/bin/env python3
"""
Attack: state_consistency | multi_config_create | config_persistence
Strategy: 1 (CRUD后COUNT一致性 - 配置多样性测试)
Endpoint: collections+create
Constraint IDs:
  - behavioral_contracts::qdrant_behavioral_create_visibility_001
  - state_invariants::qdrant_invariant_create_query_001
Source URL: https://api.qdrant.tech/api-reference/collections/create-collection
Doc Version: 1.19.x
Expected Defect Type: Type4_StateLogicViolation
Blindspot: BS-03 (Concurrency Blindness) - config state management
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

# Test different distance metrics
distance_configs = [
    ("cosine", "Cosine"),
    ("euclidean", "Euclidean"),
    ("dot", "Dot"),
    ("manhattan", "Manhattan"),
]

# Test different vector sizes
size_configs = [1, 64, 128, 256, 1024]

print("Testing multi-config creation...")

results = []
errors = []

for dist_name, distance_val in distance_configs:
    for size in size_configs:
        coll_name = f"test_config_{dist_name}_{size}"

        # Cleanup
        try:
            safe_request("DELETE", f"/collections/{coll_name}")
            time.sleep(0.03)
        except Exception:
            pass

        create_body = {
            "vectors": {
                "size": size,
                "distance": distance_val
            }
        }

        # Create
        status_c, body_c, raw_c = safe_request("PUT", f"/collections/{coll_name}", json=create_body)

        if status_c != 200:
            errors.append(f"Create failed: {coll_name} status={status_c}")
            continue

        # Verify visibility
        status_g, body_g, raw_g = safe_request("GET", f"/collections/{coll_name}")

        if status_g != 200:
            errors.append(f"Get failed: {coll_name} status={status_g}")
            results.append(False)
            continue

        # Verify config persisted correctly
        try:
            result = body_g.get("result", {})
            vectors_config = result.get("config", {}).get("params", {}).get("vectors", {})

            persisted_size = vectors_config.get("size")
            persisted_distance = vectors_config.get("distance")

            if persisted_size != size or persisted_distance != distance_val:
                errors.append(f"Config mismatch for {coll_name}: expected ({size}, {distance_val}), got ({persisted_size}, {persisted_distance})")
                results.append(False)
            else:
                results.append(True)
        except Exception as e:
            errors.append(f"Config parse error for {coll_name}: {e}")
            results.append(False)

        # Cleanup
        try:
            safe_request("DELETE", f"/collections/{coll_name}")
        except Exception:
            pass

        time.sleep(0.02)

print(f"Multi-config results: {len(results)} tested")

if errors:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Multi-config creation errors:")
    for err in errors[:5]:
        print(f"  - {err}")
    if len(errors) > 5:
        print(f"  ... and {len(errors) - 5} more")
    sys.exit(1)

success_rate = sum(results) / len(results) if results else 0
print(f"Success rate: {success_rate:.1%} ({sum(results)}/{len(results)})")

if success_rate < 1.0:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Multi-config consistency rate {success_rate:.1%} < 100%")
    sys.exit(1)

print(f"VERDICT: NO_DEFECT — All {len(results)} multi-config tests passed")
sys.exit(0)
