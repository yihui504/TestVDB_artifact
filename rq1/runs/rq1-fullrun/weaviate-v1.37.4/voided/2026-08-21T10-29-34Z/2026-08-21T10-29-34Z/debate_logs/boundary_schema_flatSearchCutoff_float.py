#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: weaviate v1.37.4
Attack: type boundary — flatSearchCutoff=float 12345.67 (declared int, default 40000)
Constraint: contract POST /schema parameter flatSearchCutoff (type int, default 40000)
exploration_target: novel_candidate
shape_id: flatSearchCutoff_type_confusion
shape_type: type_confusion
generalized_from: contract flatSearchCutoff declared int
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

CLS = "TestBoundaryFlatCutoffFloat"

def cleanup():
    try:
        rt.request("DELETE", "drop_schema", path_params={"name": CLS})
    except Exception as e:
        print(f"Cleanup warning: {e}")

def main():
    # Arrange: flatSearchCutoff=12345.67 (float where int declared; non-integer rejected 422 known)
    payload = {
        "class": CLS,
        "vectorizer": "none",
        "vectorIndexType": "hnsw",
        "vectorIndexConfig": {
            "distance": "cosine",
            "flatSearchCutoff": 12345.67
        }
    }
    status, _body, raw = rt.request("POST", "create_schema", payload)
    print(f"Status: {status}")
    print(f"Raw: {raw}")

    # A float that is semantically invalid for an int-typed config field.
    # Judge: reject(4xx)=OK; if accepted+persisted as float -> Type1.
    v = rt.judge_schema_attack(status, raw, CLS,
        ["vectorIndexConfig", "flatSearchCutoff"], 12345.67, setup_ok=True)
    print(f"VERDICT: {v}")
    sys.exit(0 if v == "NO_DEFECT" else 1 if v == "DEFECT_FOUND" else 2)

if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
