#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: weaviate v1.37.4
Attack: pairing boundary equality (dynamicEfMin == dynamicEfMax)
Constraint: weaviate_inferred_hnsw_ef_pairing_001
exploration_target: novel_candidate
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

CLS = "TestBoundaryEfEqual"

def cleanup():
    try:
        rt.request("DELETE", "drop_schema", path_params={"name": CLS})
    except Exception as e:
        print(f"Cleanup warning: {e}")

def main():
    # Arrange: Min == Max (boundary of Min<=Max; ambiguous degenerate EF range)
    payload = {
        "class": CLS,
        "vectorizer": "none",
        "vectorIndexType": "hnsw",
        "vectorIndexConfig": {
            "distance": "cosine",
            "dynamicEfMin": 300,
            "dynamicEfMax": 300
        }
    }
    status, _body, raw = rt.request("POST", "create_schema", payload)
    print(f"Status: {status}")
    print(f"Raw: {raw}")

    # Judge via schema read-back: persist original / silent normalize / drop
    v = rt.judge_schema_attack(status, raw, CLS,
        ["vectorIndexConfig", "dynamicEfMin"], 300, setup_ok=True)
    print(f"VERDICT: {v}")
    sys.exit(0 if v == "NO_DEFECT" else 1 if v == "DEFECT_FOUND" else 2)

if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
