#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.16
Attack: boundary / extra body keys on entities+insert (pass-through GT surface)
Constraint: milvus_type_entities_insert_002 + milvus_behavioral_entities_insert_003
Contract (live-confirmed): insert with nprobe=0/-5 or searchParams.nprobe=-5 ->
code 0 (keys silently dropped; NOT validated on this path).

This unit: regression of the pass-through with EXTREME values (nprobe=-1000000,
searchParams nprobe="not_a_number" type confusion). Contract says these are
ignored — code 0 with correct insertCount is by-design; 5xx/panic = Type3.
setup_default uses autoID=True so rows must NOT carry the pk field.
# exploration_target: regression
# shape_id: insert_extrakeys
# shape_type: semantic_drift
# Blindspot: BS-04 Boundary Default Optimism
"""
import os, sys

_sd = os.environ.get("TESTVDB_SCRIPTS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "scripts")
sys.path.insert(0, _sd)
from runtime import get_runtime
rt = get_runtime()

COLL = "bnd_ex_15"
DIM = 8

def main():
    ok, err = rt.setup_default(COLL, DIM)
    if not ok:
        print(f"VERDICT: SCRIPT_ERROR — setup: {err}")
        sys.exit(2)
    try:
        status, raw = rt.request("POST", "insert_points", {
            "collectionName": COLL,
            "data": [{"vector": [0.1] * DIM}],  # autoID=True: no pk field
            "nprobe": -1000000,
            "searchParams": {"nprobe": "not_a_number"}})
        print(f"Status: {status}\nRaw: {raw[:400]}")
        # by-design pass-through: expected accepted with insertCount
        v = rt.judge_200(status, raw, setup_ok=ok)
        print(f"VERDICT: {v}")
        sys.exit(0 if v == "NO_DEFECT" else 1 if v == "DEFECT_FOUND" else 2)
    finally:
        rt.drop_collection(COLL)

if __name__ == "__main__":
    main()
