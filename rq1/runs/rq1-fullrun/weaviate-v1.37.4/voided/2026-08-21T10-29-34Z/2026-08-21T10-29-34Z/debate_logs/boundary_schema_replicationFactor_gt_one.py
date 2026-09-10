#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: weaviate v1.37.4
Attack: value-boundary — replicationConfig.factor=2 (multi-node config in single-node env)
Constraint: contract POST /schema parameter replicationFactor (type int)
exploration_target: novel_candidate
shape_id: replicationFactor_numeric_boundary
shape_type: semantic_drift
generalized_from: contract replicationFactor int
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

CLS = "TestBoundaryReplicationGtOne"

def cleanup():
    try:
        rt.request("DELETE", "drop_schema", path_params={"name": CLS})
    except Exception as e:
        print(f"Cleanup warning: {e}")

def main():
    # Arrange: replicationConfig.factor=2 (requires >1 node; single-node env 422 is
    # by-design per threat model — record behavior, do not flag as defect).
    payload = {
        "class": CLS,
        "vectorizer": "none",
        "replicationConfig": {
            "factor": 2
        }
    }
    status, _body, raw = rt.request("POST", "create_schema", payload)
    print(f"Status: {status}")
    print(f"Raw: {raw}")

    # SKIPPED: by-design per threat_model if 422 single-node; factor=2 only valid in cluster.
    v = rt.judge_schema_attack(status, raw, CLS,
        ["replicationConfig", "factor"], 2, setup_ok=True)
    print(f"VERDICT: {v}")
    sys.exit(0 if v == "NO_DEFECT" else 1 if v == "DEFECT_FOUND" else 2)

if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
