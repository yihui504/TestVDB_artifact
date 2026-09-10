#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.16
Attack: boundary / type confusion — collectionName as int on collections+create
Constraint: api_endpoints collections+create parameters (collectionName: string,
required). Type confusion family (BS-01).

This unit: collectionName=123 (int). Live probe: code 1801
'json: cannot unmarshal number ... of type string' — correct type rejection.
Expected: rejected. If accepted => Type1.
# exploration_target: novel_candidate
# shape_id: name_type_confusion
# shape_type: type_confusion
# Blindspot: BS-01 Parameter Coercion Trust
"""
import os, sys

_sd = os.environ.get("TESTVDB_SCRIPTS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "scripts")
sys.path.insert(0, _sd)
from runtime import get_runtime
rt = get_runtime()

COLL = "bnd_tc_10"

def main():
    rt.drop_collection(COLL)
    try:
        status, raw = rt.request("POST", "create_collection", {
            "collectionName": 123, "dimension": 8})
        print(f"Status: {status}\nRaw: {raw[:400]}")
        v = rt.expect_rejected(status, raw, setup_ok=True)
        print(f"VERDICT: {v}")
        sys.exit(0 if v == "NO_DEFECT" else 1 if v == "DEFECT_FOUND" else 2)
    finally:
        rt.drop_collection(COLL)

if __name__ == "__main__":
    main()
