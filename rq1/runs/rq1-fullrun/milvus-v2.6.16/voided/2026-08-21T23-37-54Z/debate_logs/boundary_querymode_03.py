#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.16
Attack: boundary / query_mode via params carrier (contract api_endpoints
collections+create documents query_mode as "Collection-level property via
params/properties" — probe BOTH carriers).
Constraint: milvus_type_collections_create_009

This unit: collections+create with params.query_mode='bogus' (invalid enum).
Contract: code 65535. Live probe: code 0 (silent drop) => Type1_IllegalSuccess.
# exploration_target: regression
# shape_id: querymode_enum_family
# shape_type: semantic_drift
# Blindspot: BS-01 Parameter Validation Optimism
"""
import os, sys

_sd = os.environ.get("TESTVDB_SCRIPTS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "scripts")
sys.path.insert(0, _sd)
from runtime import get_runtime
rt = get_runtime()

SCHEMA = {"fields": [
    {"fieldName": "id", "dataType": "Int64", "isPrimary": True, "autoID": True},
    {"fieldName": "vector", "dataType": "FloatVector",
     "elementTypeParams": {"dim": 8}},
]}
COLL = "bnd_qm_03"

def main():
    rt.drop_collection(COLL)
    try:
        status, raw = rt.request("POST", "create_collection", {
            "collectionName": COLL, "schema": SCHEMA,
            "params": {"query_mode": "bogus"}})
        print(f"Status: {status}\nRaw: {raw[:400]}")
        v = rt.expect_rejected(status, raw, setup_ok=True)
        print(f"VERDICT: {v}")
        sys.exit(0 if v == "NO_DEFECT" else 1 if v == "DEFECT_FOUND" else 2)
    finally:
        rt.drop_collection(COLL)

if __name__ == "__main__":
    main()
