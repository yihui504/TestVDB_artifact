#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.16
Attack: boundary / vector dimension below minimum (quick mode)
Constraint: milvus_range_collections_create_001 (dim <= 32768; live probe shows
effective range "2 ~ 32768").

This unit: dimension=0 (also -1 live-confirmed rejected). Expected: rejected.
If accepted => Type1_IllegalSuccess.
# exploration_target: regression
# shape_id: dimension_range
# shape_type: numeric_boundary
"""
import os, sys

_sd = os.environ.get("TESTVDB_SCRIPTS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "scripts")
sys.path.insert(0, _sd)
from runtime import get_runtime
rt = get_runtime()

COLL = "bnd_dim_12"

def main():
    rt.drop_collection(COLL)
    try:
        status, raw = rt.request("POST", "create_collection", {
            "collectionName": COLL, "dimension": 0, "metricType": "L2",
            "idType": "Int64", "autoID": True, "vectorFieldType": "FloatVector"})
        print(f"Status: {status}\nRaw: {raw[:400]}")
        v = rt.expect_rejected(status, raw, setup_ok=True)
        print(f"VERDICT: {v}")
        sys.exit(0 if v == "NO_DEFECT" else 1 if v == "DEFECT_FOUND" else 2)
    finally:
        rt.drop_collection(COLL)

if __name__ == "__main__":
    main()
