#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: weaviate v1.37.4
Attack: resource-limit extreme boundary (flatSearchCutoff=1e9, default 40000)
Constraint: contract POST /schema parameter flatSearchCutoff (type int, default 40000)
exploration_target: novel_candidate
shape_id: flatSearchCutoff_numeric_boundary
shape_type: resource_limit
generalized_from: contract flatSearchCutoff default 40000
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

CLS = "TestBoundaryFlatCutoffExtreme"

def cleanup():
    try:
        rt.request("DELETE", "drop_schema", path_params={"name": CLS})
    except Exception as e:
        print(f"Cleanup warning: {e}")

def main():
    # Arrange: flatSearchCutoff=1e9 (extreme upper bound; potential overflow path)
    payload = {
        "class": CLS,
        "vectorizer": "none",
        "vectorIndexType": "hnsw",
        "vectorIndexConfig": {
            "distance": "cosine",
            "flatSearchCutoff": 1000000000
        }
    }
    status, _body, raw = rt.request("POST", "create_schema", payload)
    print(f"Status: {status}")
    print(f"Raw: {raw}")

    # Extreme value accepted persists as-is (Type1 if stored raw, since no documented cap);
    # exteme accept is NO_DEFECT unless read-back crashes. judge_schema_attack compares persist.
    v = rt.judge_schema_attack(status, raw, CLS,
        ["vectorIndexConfig", "flatSearchCutoff"], 1000000000, setup_ok=True)
    print(f"VERDICT: {v}")
    sys.exit(0 if v == "NO_DEFECT" else 1 if v == "DEFECT_FOUND" else 2)

if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
