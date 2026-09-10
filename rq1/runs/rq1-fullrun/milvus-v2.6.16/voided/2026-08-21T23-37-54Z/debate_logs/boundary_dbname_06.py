#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.16
Attack: boundary / dbName nonexistent matrix (write path)
Constraint: milvus_state_collections_create_002
Contract: NOT exists(dbName) AND collections/create => code 800
'database not found[database=<dbName>]' (live-confirmed v2.6.16).

This unit: collections+create with dbName=bnd_nodb_9527.
Expected: rejected (800). Live probe confirmed 800.
# exploration_target: regression
# shape_id: dbname_matrix
# shape_type: semantic_drift
"""
import os, sys

_sd = os.environ.get("TESTVDB_SCRIPTS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "scripts")
sys.path.insert(0, _sd)
from runtime import get_runtime
rt = get_runtime()

COLL = "bnd_db_06"

def main():
    try:
        status, raw = rt.request("POST", "create_collection", {
            "collectionName": COLL, "dbName": "bnd_nodb_9527", "dimension": 8,
            "metricType": "L2", "idType": "Int64", "autoID": True,
            "vectorFieldType": "FloatVector"})
        print(f"Status: {status}\nRaw: {raw[:400]}")
        v = rt.expect_rejected(status, raw, setup_ok=True)
        print(f"VERDICT: {v}")
        sys.exit(0 if v == "NO_DEFECT" else 1 if v == "DEFECT_FOUND" else 2)
    finally:
        rt.drop_collection(COLL)

if __name__ == "__main__":
    main()
