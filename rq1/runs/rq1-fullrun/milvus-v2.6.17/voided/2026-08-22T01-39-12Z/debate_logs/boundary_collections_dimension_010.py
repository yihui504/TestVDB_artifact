#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.17
Attack: boundary (range+type) - collections+create dimension: 0, -1, 32769 (max+1), 32768 (max), "abc", null, float 7.5, string "8", INT32_MAX+1; quick-mode and full-schema elementTypeParams.dim variants
Constraint: milvus_range_collections_create_001 (dim <= 32768)
Source: .milvus-src-2617/internal/distributed/proxy/httpserver/handler_v2.go
Doc Version: v2.6.17
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import safe_request, code_of, drop_collection

def ok(b):
    return code_of(b) == 0

def full_create(col, dim):
    return safe_request("POST", "collections+create", {
        "collectionName": col,
        "schema": {"fields": [
            {"fieldName": "id", "dataType": "Int64", "isPrimary": True, "elementTypeParams": {}},
            {"fieldName": "vec", "dataType": "FloatVector",
             "elementTypeParams": {"dim": dim}},
        ], "enableDynamicField": True},
    })

def main():
    base = "bnd_dim_010"
    defects = []
    quick_cases = [
        ("dim 0", 0, False), ("dim -1", -1, False),
        ("dim 32768 (max)", 32768, True), ("dim 32769 (max+1)", 32769, False),
        ("dim 1e6", 1000000, False),
        ("dim 'abc'", "abc", False), ("dim null", None, False),
        ("dim 7.5", 7.5, False), ("dim '8' str", "8", None),
        ("dim 2147483648 (int32+1)", 2147483648, False),
    ]
    for i, (label, dim, expect_ok) in enumerate(quick_cases):
        col = "%s_q%d" % (base, i)
        drop_collection(col)
        s, b, raw = safe_request("POST", "collections+create",
                                 {"collectionName": col, "dimension": dim})
        c = code_of(b)
        print("quick %s -> code=%s raw=%s" % (label, c, raw[:180]))
        if expect_ok is False and ok(b):
            defects.append("quick create with %s accepted (code 0), contract: dim<=32768 and positive" % label)
        if expect_ok is True and not ok(b):
            print("  NOTE: legal max dim 32768 rejected (code=%s) - judge candidate" % c)
        drop_collection(col)

    full_cases = [("dim 0", "0", False), ("dim -1", "-1", False),
                  ("dim 32769", "32769", False), ("dim 'abc'", "abc", False),
                  ("dim empty str", "", False)]
    for i, (label, dim, expect_ok) in enumerate(full_cases):
        col = "%s_f%d" % (base, i)
        drop_collection(col)
        s, b, raw = full_create(col, dim)
        c = code_of(b)
        print("full %s -> code=%s raw=%s" % (label, c, raw[:180]))
        if expect_ok is False and ok(b):
            defects.append("full-schema create with %s accepted (code 0)" % label)
        drop_collection(col)

    if defects:
        for d in defects:
            print("DEFECT: %s" % d)
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - dimension range/type violation accepted")
    else:
        print("VERDICT: NO_DEFECT")

if __name__ == "__main__":
    main()
