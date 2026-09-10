#!/usr/bin/env python3
"""
Attack: state_consistency | create_config_combos | config_interaction
Strategy: 1 (CRUD后COUNT一致性 - 配置交互测试)
Endpoint: collections+create
Constraint IDs:
  - range_constraints::qdrant_range_create_collection_001
  - range_constraints::qdrant_range_create_collection_002
  - behavioral_contracts::qdrant_behavioral_create_visibility_001
Source URL: https://api.qdrant.tech/api-reference/collections/create-collection
Doc Version: 1.19.x
Expected Defect Type: Type4_StateLogicViolation
Blindspot: BS-03 (Concurrency Blindness) - config state interaction
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

# Test different HNSW configurations
hnsw_configs = [
    ("minimal", {"m": 2, "ef_construct": 10}),
    ("default", {"m": 16, "ef_construct": 100}),
    ("quality", {"m": 32, "ef_construct": 500}),
    ("max_m", {"m": 100, "ef_construct": 100}),
    ("max_ef", {"m": 16, "ef_construct": 1000}),
]

# Test different optimizer configs
optimizer_configs = [
    ("default", {"indexing_threshold": 20000}),
    ("minimal", {"indexing_threshold": 0}),
    ("high", {"indexing_threshold": 100000}),
]

# Test with on_disk flag
on_disk_flags = [True, False]

print("Testing config combinations...")

results = []
errors = []

coll_counter = 0

for hnsw_name, hnsw_config in hnsw_configs:
    for opt_name, optimizer_config in optimizer_configs:
        for on_disk in on_disk_flags:
            coll_name = f"test_combo_{hnsw_name}_{opt_name}_disk{on_disk}"

            # Cleanup
            try:
                safe_request("DELETE", f"/collections/{coll_name}")
                time.sleep(0.02)
            except Exception:
                pass

            create_body = {
                "vectors": {
                    "size": 128,
                    "distance": "Cosine"
                },
                "hnsw_config": hnsw_config,
                "optimizers_config": optimizer_config,
                "on_disk": on_disk
            }

            # Create
            status_c, body_c, raw_c = safe_request("PUT", f"/collections/{coll_name}", json=create_body)
            coll_counter += 1

            if status_c != 200:
                errors.append(f"Create failed for {coll_name}: status {status_c}")
                results.append(False)
                continue

            # Verify config persisted
            status_g, body_g, raw_g = safe_request("GET", f"/collections/{coll_name}")

            if status_g != 200:
                errors.append(f"Get failed for {coll_name}: status {status_g}")
                results.append(False)
                continue

            # Verify all configs match
            try:
                result = body_g.get("result", {})
                config = result.get("config", {}).get("params", {})

                persisted_hnsw = config.get("hnsw_config", {})
                persisted_opt = config.get("optimizers_config", {})
                persisted_on_disk = config.get("on_disk", False)

                # Check HNSW
                if persisted_hnsw.get("m") != hnsw_config.get("m"):
                    errors.append(f"HNSW m mismatch for {coll_name}: expected {hnsw_config.get('m')}, got {persisted_hnsw.get('m')}")
                    results.append(False)
                    continue

                if persisted_hnsw.get("ef_construct") != hnsw_config.get("ef_construct"):
                    errors.append(f"HNSW ef mismatch for {coll_name}: expected {hnsw_config.get('ef_construct')}, got {persisted_hnsw.get('ef_construct')}")
                    results.append(False)
                    continue

                # Check optimizer
                if persisted_opt.get("indexing_threshold") != optimizer_config.get("indexing_threshold"):
                    errors.append(f"Optimizer mismatch for {coll_name}: expected {optimizer_config.get('indexing_threshold')}, got {persisted_opt.get('indexing_threshold')}")
                    results.append(False)
                    continue

                # Check on_disk
                if persisted_on_disk != on_disk:
                    errors.append(f"on_disk mismatch for {coll_name}: expected {on_disk}, got {persisted_on_disk}")
                    results.append(False)
                    continue

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

print(f"\nConfig combination test completed: {coll_counter} collections tested")

if errors:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Config combination errors:")
    for err in errors[:5]:
        print(f"  - {err}")
    if len(errors) > 5:
        print(f"  ... and {len(errors) - 5} more")
    sys.exit(1)

success_rate = sum(results) / len(results) if results else 0
print(f"Success rate: {success_rate:.1%} ({sum(results)}/{len(results)})")

if success_rate < 1.0:
    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Config persistence consistency rate {success_rate:.1%} < 100%")
    sys.exit(1)

print(f"VERDICT: NO_DEFECT — All {len(results)} config combination tests passed")
sys.exit(0)
