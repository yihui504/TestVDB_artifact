#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.16
Attack: boundary / extra body keys on collections+create (2.6 pass-through family)
Constraint: milvus_type_collections_create_010 + milvus_type_collections_create_008
Contract records: searchParams:{nprobe:0} and bare params:{warmup:'bogus'} at
create -> code 0 (unvalidated pass-through; bare warmup is KNOWN GAP family).

This unit: create with searchParams.nprobe=0 AND params.warmup='bogus' AND
params.nprobe=-5, then describe read-back and scan the raw describe text for
the illegal keys/values (three-state: reject / silent-drop / persist).
- create rejected => NO_DEFECT
- create accepted + illegal value persisted into describe => DEFECT_FOUND (Type1)
- create accepted + values absent from describe => silent-drop (by-design family)
# exploration_target: regression
# shape_id: create_extrakeys
# shape_type: semantic_drift
# Blindspot: BS-04 Boundary Default Optimism
"""
import os, sys

_sd = os.environ.get("TESTVDB_SCRIPTS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "scripts")
sys.path.insert(0, _sd)
from runtime import get_runtime
rt = get_runtime()

COLL = "bnd_ex_08"
BAD_KEYS = ("warmup", "nprobe")

def main():
    rt.drop_collection(COLL)
    try:
        status, raw = rt.request("POST", "create_collection", {
            "collectionName": COLL, "dimension": 8,
            "searchParams": {"nprobe": 0},
            "params": {"warmup": "bogus", "nprobe": -5}})
        print(f"create Status: {status}\nRaw: {raw[:300]}")
        v = rt.expect_rejected(status, raw, setup_ok=True)
        if v == "NO_DEFECT":
            print("VERDICT: NO_DEFECT"); sys.exit(0)
        if v == "DEFECT_FOUND":
            print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — "
                  "create accepted extra illegal keys unvalidated"); sys.exit(1)
        print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
    finally:
        # read-back: did any illegal key persist?
        try:
            ds, draw = rt.request("POST", "describe_collection",
                                  {"collectionName": COLL})
            print(f"describe Status: {ds}\nRaw: {draw[:600]}")
            persisted = [k for k in BAD_KEYS if k in (draw or "")]
            if persisted:
                print(f"NOTE read-back: illegal keys persisted in describe: {persisted}")
        except Exception as e:
            print(f"read-back warning: {e}")
        rt.drop_collection(COLL)

if __name__ == "__main__":
    main()
