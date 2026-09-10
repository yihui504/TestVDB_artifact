#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.16
Attack: boundary / enum validation (query_mode property family, 2.6.14+)
Constraint: milvus_type_collections_create_009
Contract: properties/params.query_mode NOT IN {unset,'large_topk'} => code 65535
"invalid query_mode value ..., valid values: [large_topk]" (live-confirmed v2.6.16 for 'bogus').

This unit: collections+create with schema mode + properties.query_mode='bogus'.
Live probe suggested create-time validation is BYPASSED (code 0, silent drop).
Expected: rejected (code 65535). If accepted => Type1_IllegalSuccess.
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
COLL = "bnd_qm_01"

def main():
    rt.drop_collection(COLL)
    try:
        status, raw = rt.request("POST", "create_collection", {
            "collectionName": COLL, "schema": SCHEMA,
            "properties": {"query_mode": "bogus"}})
        print(f"Status: {status}\nRaw: {raw[:400]}")
        v = rt.expect_rejected(status, raw, setup_ok=True)
        print(f"VERDICT: {v}")
        sys.exit(0 if v == "NO_DEFECT" else 1 if v == "DEFECT_FOUND" else 2)
    finally:
        rt.drop_collection(COLL)

if __name__ == "__main__":
    main()
