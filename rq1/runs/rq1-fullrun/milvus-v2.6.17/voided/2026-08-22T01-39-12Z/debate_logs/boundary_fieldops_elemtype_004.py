#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.17
Attack: type boundary - fieldOps ARRAY_APPEND/ARRAY_REMOVE element-type confusion: append non-VarChar elements (int/float/bool/null/nested list/dict) to Array<VarChar> field; expect 1100; accept+persist = Type1
Constraint: milvus_type_entities_upsert_fieldops_001/002 + Array elementDataType typing
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
            {"fieldName": "tags", "dataType": "Array", "elementDataType": "VarChar",
             "elementTypeParams": {"max_capacity": "64", "max_length": "64"}},
        ], "enableDynamicField": True},
        "indexParams": [{"fieldName": "vec", "indexName": "vec_idx", "metricType": "L2"}],
    })
    if not ok(b):
        return s, b, raw
    s, b, raw = safe_request("POST", "collections+load", {"collectionName": col})
    if not ok(b):
        return s, b, raw
    return safe_request("POST", "entities+insert", {"collectionName": col, "data": [
        {"id": 1, "vec": [0.1] * 8, "tags": ["a", "b"]},
    ]})

def main():
    col = "bnd_fieldops_etype_004"
    s, b, raw = setup_col(col)
    if not ok(b):
        print("VERDICT: SCRIPT_ERROR - setup failed: %s" % raw[:300]); return

    bad_values = [
        ("int elem", [42]),
        ("float elem", [1.5]),
        ("bool elem", [True]),
        ("null elem", [None]),
        ("nested list", [["inner"]]),
        ("dict elem", [{"k": "v"}]),
        ("mixed", ["ok", 7, None]),
    ]
    defects = []
    for label, val in bad_values:
        s, b, raw = safe_request("POST", "entities+upsert", {
            "collectionName": col,
            "data": [{"id": 1, "tags": val}],
            "partialUpdate": True,
            "fieldOps": [{"fieldName": "tags", "op": "ARRAY_APPEND"}],
        })
        print("%s -> code=%s raw=%s" % (label, code_of(b), raw[:220]))
        if ok(b):
            s2, b2, r2 = query_all(col, "id == 1", output_fields=["tags"])
            rows = (b2 or {}).get("data") or []
            if rows and "tags" in rows[0]:
                print("  readback tags=%r" % (rows[0]["tags"],))
                defects.append("%s accepted & persisted into Array<VarChar>: %r" % (label, rows[0]["tags"]))
            else:
                print("  NOTE: accepted but element not readback-able (silent drop - judge candidate)")

    try:
        drop_collection(col)
    except Exception:
        pass

    if defects:
        for d in defects:
            print("DEFECT: %s" % d)
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - mistyped elements accepted into typed Array")
    else:
        print("VERDICT: NO_DEFECT")

if __name__ == "__main__":
    main()
