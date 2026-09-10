#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.16
Attack: boundary / read-back verification of valid query_mode at create
Constraint: milvus_range_entities_search_003 (query_mode==large_topk: limit<=1000000)
+ milvus_type_collections_create_009 (query_mode property family at create)

This unit: create (schema mode, no indexParams) with properties.query_mode='large_topk',
then index+load, then search limit=100000. Contract says large_topk raises TopKLimit
to 1000000 (live-confirmed for the alter path). If create-time setting is silently
dropped (live probe: describe shows only timezone; limit 100000 -> 65535 [1,16384]),
the create-time property path is ineffective => semantic defect (valid setting dropped).
Expected: accepted (code 0). If rejected => DEFECT.
# exploration_target: regression
# shape_id: querymode_enum_family
# shape_type: semantic_drift
"""
import os, sys, time

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
COLL = "bnd_qm_02"

def main():
    rt.drop_collection(COLL)
    try:
        s, raw = rt.request("POST", "create_collection", {
            "collectionName": COLL, "schema": SCHEMA,
            "properties": {"query_mode": "large_topk"}})
        print(f"create: {s} {raw[:200]}")
        if s != 200 or '"code":0' not in raw:
            print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
        rt.request("POST", "create_index", {"collectionName": COLL, "indexParams": [{
            "fieldName": "vector", "indexName": "v", "indexType": "HNSW",
            "metricType": "L2", "params": {"M": 16, "efConstruction": 200}}]})
        rt.request("POST", "load_collection", {"collectionName": COLL})
        time.sleep(float(os.environ.get("TESTVDB_LOAD_WAIT", "2")))
        status, raw = rt.request("POST", "search", {
            "collectionName": COLL,
            "data": [[0.1] * 8], "limit": 100000})
        print(f"Status: {status}\nRaw: {raw[:400]}")
        v = rt.judge_200(status, raw, setup_ok=True)
        print(f"VERDICT: {v}")
        sys.exit(0 if v == "NO_DEFECT" else 1 if v == "DEFECT_FOUND" else 2)
    finally:
        rt.drop_collection(COLL)

if __name__ == "__main__":
    main()
