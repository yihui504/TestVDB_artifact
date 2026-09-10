#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: weaviate v1.37.4
Attack: inverted pairing boundary (dynamicEfMin > dynamicEfMax)
Constraint: weaviate_inferred_hnsw_ef_pairing_001
exploration_target: regression
shape_id: ef_pairing_numeric_boundary
shape_type: numeric_boundary
generalized_from: weaviate_inferred_hnsw_ef_pairing_001
"""

import os
import sys

# Windows encoding compatibility
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_sd = os.environ.get("TESTVDB_SCRIPTS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, _sd)

from runtime import get_runtime  # weaviate target runtime (contract-driven)
rt = get_runtime()

CLS = "TestBoundaryEfInverted"

def cleanup():
    try:
        rt.request("DELETE", "drop_schema", path_params={"name": CLS})
    except Exception as e:
        print(f"Cleanup warning: {e}")

def main():
    # Arrange: inverted EF range (Min=250 > Max=100) violates pairing constraint
    payload = {
        "class": CLS,
        "vectorizer": "none",
        "vectorIndexType": "hnsw",
        "vectorIndexConfig": {
            "distance": "cosine",
            "dynamicEfMin": 250,
            "dynamicEfMax": 100
        }
    }
    status, _body, raw = rt.request("POST", "create_schema", payload)
    print(f"Status: {status}")
    print(f"Raw: {raw}")

    v = rt.judge_schema_attack(status, raw, CLS,
        ["vectorIndexConfig", "dynamicEfMin"], 250, setup_ok=True)
    print(f"VERDICT: {v}")
    sys.exit(0 if v == "NO_DEFECT" else 1 if v == "DEFECT_FOUND" else 2)

if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
