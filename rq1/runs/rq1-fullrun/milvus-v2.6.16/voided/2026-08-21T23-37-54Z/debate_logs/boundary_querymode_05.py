#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.16
Attack: boundary / large_topk quota window coupling (offset+limit window)
Constraint: milvus_range_entities_search_003
Contract: query_mode==large_topk => 1 <= limit+offset <= 1000000 else 65535
"it should be in range [1, 1000000], but got %d".

This unit: alter query_mode='large_topk' on index-free schema-mode collection,
index+load, then search limit=500000 offset=500001 (window 1000002 > 1000000).
Expected: rejected (65535). If accepted => Type1.
# exploration_target: novel_candidate (window edge, live-confirmed only single-limit edges)
# shape_id: querymode_quota_coupling
# shape_type: numeric_boundary
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
COLL = "bnd_qm_05"

def main():
    rt.drop_collection(COLL)
    try:
        s, raw = rt.request("POST", "create_collection",
                            {"collectionName": COLL, "schema": SCHEMA})
        if s != 200 or '"code":0' not in raw:
            print(f"create failed: {s} {raw[:150]}\nVERDICT: SCRIPT_ERROR"); sys.exit(2)
        # alter BEFORE index exists (contract: index-free alter is the valid path)
        s, raw = rt.request("POST", "collections+alter_properties", {
            "collectionName": COLL, "properties": {"query_mode": "large_topk"}})
        print(f"alter: {s} {raw[:200]}")
        rt.request("POST", "create_index", {"collectionName": COLL, "indexParams": [{
            "fieldName": "vector", "indexName": "v", "indexType": "HNSW",
            "metricType": "L2", "params": {"M": 16, "efConstruction": 200}}]})
        rt.request("POST", "load_collection", {"collectionName": COLL})
        time.sleep(float(os.environ.get("TESTVDB_LOAD_WAIT", "2")))
        status, raw = rt.request("POST", "search", {
            "collectionName": COLL, "data": [[0.1] * 8],
            "limit": 500000, "offset": 500001})
        print(f"Status: {status}\nRaw: {raw[:400]}")
        v = rt.expect_rejected(status, raw, setup_ok=True)
        print(f"VERDICT: {v}")
        sys.exit(0 if v == "NO_DEFECT" else 1 if v == "DEFECT_FOUND" else 2)
    finally:
        rt.drop_collection(COLL)

if __name__ == "__main__":
    main()
