#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.17
Attack: boundary (enum/target) - ARRAY_APPEND/ARRAY_REMOVE on non-Array fields (Int64, VarChar, FloatVector, JSON, dynamic); contract: 1100 'op <OP> requires Array field'
Constraint: milvus_type_entities_upsert_fieldops_002
Source: .milvus-src-2617/internal/distributed/proxy/httpserver/handler_v2.go
Doc Version: v2.6.17
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import safe_request, code_of, drop_collection, query_all

def ok(b):
    return code_of(b) == 0

def setup_col(col):
    drop_collection(col)
    s, b, raw = safe_request("POST", "collections+create", {
        "collectionName": col,
        "schema": {"fields": [
            {"fieldName": "id", "dataType": "Int64", "isPrimary": True, "elementTypeParams": {}},
            {"fieldName": "vec", "dataType": "FloatVector", "elementTypeParams": {"dim": "8"}},
            {"fieldName": "title", "dataType": "VarChar", "elementTypeParams": {"max_length": "64"}},
            {"fieldName": "tags", "dataType": "Array", "elementDataType": "VarChar",
             "elementTypeParams": {"max_capacity": "64", "max_length": "64"}},
            {"fieldName": "meta", "dataType": "JSON", "elementTypeParams": {}},
        ], "enableDynamicField": True},
        "indexParams": [{"fieldName": "vec", "indexName": "vec_idx", "metricType": "L2"}],
    })
    if not ok(b):
        return s, b, raw
    s, b, raw = safe_request("POST", "collections+load", {"collectionName": col})
    if not ok(b):
        return s, b, raw
    return safe_request("POST", "entities+insert", {"collectionName": col, "data": [
        {"id": 1, "vec": [0.1] * 8, "title": "t", "tags": ["a"], "meta": {"k": 1}, "dyn": 5},
    ]})

def main():
    col = "bnd_fieldops_array_tgt_002"
    s, b, raw = setup_col(col)
    if not ok(b):
        print("VERDICT: SCRIPT_ERROR - setup failed: %s" % raw[:300]); return

    targets = ["title", "meta", "vec", "dyn"]  # VarChar, JSON, FloatVector, dynamic int
    defects = []
    for fld in targets:
        for op in ("ARRAY_APPEND", "ARRAY_REMOVE"):
            payload_data = [{"id": 1, fld: ["x"]}]
            s, b, raw = safe_request("POST", "entities+upsert", {
                "collectionName": col,
                "data": payload_data,
                "partialUpdate": True,
                "fieldOps": [{"fieldName": fld, "op": op}],
            })
            c = code_of(b)
            print("%s on %s -> code=%s raw=%s" % (op, fld, c, raw[:220]))
            if ok(b):
                defects.append("%s accepted on non-Array field %s (code 0), contract requires 1100" % (op, fld))
            else:
                if "requires Array field" not in raw:
                    print("  NOTE: rejected but message lacks 'requires Array field' (Type2 candidate)")
                # verify no partial write occurred
                s2, b2, r2 = query_all(col, "id == 1", output_fields=[fld])
                if ok(b2):
                    rows = (b2.get("data") or [])
                    if rows and fld in rows[0]:
                        print("  LEAK-CHECK: field %s now = %r (should be untouched)" % (fld, rows[0][fld]))

    try:
        drop_collection(col)
    except Exception:
        pass

    if defects:
        for d in defects:
            print("DEFECT: %s" % d)
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - ARRAY_* op accepted on non-Array field")
    else:
        print("VERDICT: NO_DEFECT")

if __name__ == "__main__":
    main()
