#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.17
Attack: boundary (enum/type) - schema dataType enum: bogus 'FloatVector32', empty, lowercase 'int64', null, missing dataType; Array without elementDataType; BinaryVector dim 12 (not %8); missing fieldName; quick/full mode conflict (dimension + schema)
Constraint: milvus_type_collections_create_001/002/003/005/006
Source: .milvus-src-2617/internal/distributed/proxy/httpserver/handler_v2.go
Doc Version: v2.6.17
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import safe_request, code_of, drop_collection

def ok(b):
    return code_of(b) == 0

def create_with_fields(col, fields):
    return safe_request("POST", "collections+create", {
        "collectionName": col,
        "schema": {"fields": fields, "enableDynamicField": True},
    })

def main():
    base = "bnd_dt_016"
    idf = {"fieldName": "id", "dataType": "Int64", "isPrimary": True, "elementTypeParams": {}}
    vecf = {"fieldName": "vec", "dataType": "FloatVector", "elementTypeParams": {"dim": "8"}}
    defects = []

    cases = [
        ("bogus dataType FloatVector32",
         [idf, vecf, {"fieldName": "x", "dataType": "FloatVector32", "elementTypeParams": {}}], False),
        ("dataType empty",
         [idf, vecf, {"fieldName": "x", "dataType": "", "elementTypeParams": {}}], False),
        ("dataType lowercase int64",
         [idf, vecf, {"fieldName": "x", "dataType": "int64", "elementTypeParams": {}}], False),
        ("dataType null",
         [idf, vecf, {"fieldName": "x", "dataType": None, "elementTypeParams": {}}], False),
        ("dataType missing",
         [idf, vecf, {"fieldName": "x", "elementTypeParams": {}}], False),
        ("fieldName missing",
         [idf, vecf, {"dataType": "Int64", "elementTypeParams": {}}], False),
        ("Array without elementDataType",
         [idf, vecf, {"fieldName": "arr", "dataType": "Array",
                      "elementTypeParams": {"max_capacity": "16", "max_length": "16"}}], False),
        ("BinaryVector dim 12 (not %8)",
         [idf, {"fieldName": "bvec", "dataType": "BinaryVector", "elementTypeParams": {"dim": "12"}}], False),
    ]
    for i, (label, fields, expect_ok) in enumerate(cases):
        col = "%s_%d" % (base, i)
        drop_collection(col)
        s, b, raw = create_with_fields(col, fields)
        c = code_of(b)
        print("%s -> code=%s raw=%s" % (label, c, raw[:200]))
        if expect_ok is False and ok(b):
            defects.append("schema with %s accepted (code 0)" % label)
        drop_collection(col)

    # quick/full mode conflict: dimension + schema
    col = base + "_conflict"
    drop_collection(col)
    s, b, raw = safe_request("POST", "collections+create", {
        "collectionName": col, "dimension": 8,
        "schema": {"fields": [idf, vecf]}})
    print("quick+full conflict -> code=%s raw=%s" % (code_of(b), raw[:200]))
    if ok(b):
        defects.append("quick/full mode conflict accepted (contract: code 1100)")
    drop_collection(col)

    if defects:
        for d in defects:
            print("DEFECT: %s" % d)
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - invalid schema accepted")
    else:
        print("VERDICT: NO_DEFECT")

if __name__ == "__main__":
    main()
