#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.16
Attack: boundary / collection name length limit (max 255)
Constraint: milvus_range_collections_create_002
Contract: collection/field/partition/alias/db name max length 255
(proxy.maxNameLength).

This unit: collectionName of 256 chars. Expected: rejected (out of range).
If accepted => Type1_IllegalSuccess.
# exploration_target: regression
# shape_id: name_length
# shape_type: numeric_boundary
"""
import os, sys

_sd = os.environ.get("TESTVDB_SCRIPTS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "scripts")
sys.path.insert(0, _sd)
from runtime import get_runtime
rt = get_runtime()

LONG_NAME = "bnd_long_" + "a" * 248  # 9 + 248 = 257 chars > 255

def main():
    try:
        status, raw = rt.request("POST", "create_collection", {
            "collectionName": LONG_NAME, "dimension": 8})
        print(f"Status: {status}\nRaw: {raw[:400]}")
        v = rt.expect_rejected(status, raw, setup_ok=True)
        print(f"VERDICT: {v}")
        sys.exit(0 if v == "NO_DEFECT" else 1 if v == "DEFECT_FOUND" else 2)
    finally:
        rt.drop_collection(LONG_NAME)

if __name__ == "__main__":
    main()
