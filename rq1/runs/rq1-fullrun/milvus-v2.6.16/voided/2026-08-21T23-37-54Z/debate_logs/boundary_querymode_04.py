#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.16
Attack: boundary / query_mode <-> index interaction (2.6 new surface)
Constraint: milvus_range_collections_querymode_001
Contract: collection has vector index AND alter_properties sets query_mode
=> code 702 "can not alter query_mode if the collection already has a vector
index. Please drop the index first".

This unit: quick-create (auto index) then alter_properties query_mode='large_topk'.
Expected: rejected (702). Live probe confirmed 702 on schema-mode+index too.
# exploration_target: regression
# shape_id: querymode_index_interaction
# shape_type: semantic_drift
"""
import os, sys

_sd = os.environ.get("TESTVDB_SCRIPTS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "scripts")
sys.path.insert(0, _sd)
from runtime import get_runtime
rt = get_runtime()

COLL = "bnd_qm_04"

def main():
    rt.drop_collection(COLL)
    try:
        # quick-create auto-creates a vector index (per contract note)
        s, raw = rt.request("POST", "create_collection", {
            "collectionName": COLL, "dimension": 8, "metricType": "L2",
            "idType": "Int64", "autoID": True, "vectorFieldType": "FloatVector"})
        print(f"setup create: {s} {raw[:150]}")
        if s != 200 or '"code":0' not in raw:
            print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
        status, raw = rt.request("POST", "collections+alter_properties", {
            "collectionName": COLL,
            "properties": {"query_mode": "large_topk"}})
        print(f"Status: {status}\nRaw: {raw[:400]}")
        v = rt.expect_rejected(status, raw, setup_ok=True)
        print(f"VERDICT: {v}")
        sys.exit(0 if v == "NO_DEFECT" else 1 if v == "DEFECT_FOUND" else 2)
    finally:
        rt.drop_collection(COLL)

if __name__ == "__main__":
    main()
