#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.16
Attack: boundary / search limit upper bound on normal-mode collection
Constraint: milvus_range_entities_search_001
Contract: normal mode (no large_topk): 1 <= limit+offset <= 16384 else code 65535
'it should be in range [1, 16384], but got %d'. Live: limit 20000 -> 65535.

This unit: limit=16385 (max+1 boundary edge). Expected: rejected (65535).
If accepted => Type1_IllegalSuccess.
# exploration_target: regression
# shape_id: search_limit_range
# shape_type: numeric_boundary
"""
import os, sys

_sd = os.environ.get("TESTVDB_SCRIPTS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "scripts")
sys.path.insert(0, _sd)
from runtime import get_runtime
rt = get_runtime()

COLL = "bnd_sl_13"
DIM = 8

def main():
    ok, err = rt.setup_default(COLL, DIM)
    if not ok:
        print(f"VERDICT: SCRIPT_ERROR — setup: {err}")
        sys.exit(2)
    try:
        status, raw = rt.request("POST", "search", {
            "collectionName": COLL, "data": [[0.1] * DIM], "limit": 16385})
        print(f"Status: {status}\nRaw: {raw[:400]}")
        v = rt.expect_rejected(status, raw, setup_ok=ok)
        print(f"VERDICT: {v}")
        sys.exit(0 if v == "NO_DEFECT" else 1 if v == "DEFECT_FOUND" else 2)
    finally:
        rt.drop_collection(COLL)

if __name__ == "__main__":
    main()
