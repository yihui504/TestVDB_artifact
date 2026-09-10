#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.17
Attack: boundary (enum) - entities+upsert fieldOps[].op enum case/trim matrix; contract says case-insensitive+trim accepted, anything else -> 1100 'unsupported partial update op'
Constraint: milvus_type_entities_upsert_fieldops_001
Source: .milvus-src-2617/internal/distributed/proxy/httpserver/handler_v2.go
Doc Version: v2.6.17
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import safe_request, code_of, drop_collection

def ok(b):
    return code_of(b) == 0

def setup_col(col, extra_fields=None):
    drop_collection(col)
    fields = [
        {"fieldName": "id", "dataType": "Int64", "isPrimary": True, "elementTypeParams": {}},
        {"fieldName": "vec", "dataType": "FloatVector", "elementTypeParams": {"dim": "8"}},
        {"fieldName": "tags", "dataType": "Array", "elementDataType": "VarChar",
         "elementTypeParams": {"max_capacity": "64", "max_length": "64"}},
    ]
    if extra_fields:
        fields.extend(extra_fields)
    s, b, raw = safe_request("POST", "collections+create", {
        "collectionName": col,
        "schema": {"fields": fields, "enableDynamicField": True},
        "indexParams": [{"fieldName": "vec", "indexName": "vec_idx", "metricType": "L2"}],
    })
    if not ok(b):
        return s, b, raw
    return safe_request("POST", "collections+load", {"collectionName": col})

def main():
    col = "bnd_fieldops_op_enum_001"
    s, b, raw = setup_col(col)
    if not ok(b):
        print("VERDICT: SCRIPT_ERROR - setup failed: %s" % raw[:300]); return
    s, b, raw = safe_request("POST", "entities+insert", {"collectionName": col, "data": [
        {"id": 1, "vec": [0.1] * 8, "tags": ["a", "b"]},
    ]})
    if not ok(b):
        print("VERDICT: SCRIPT_ERROR - seed failed: %s" % raw[:300]); return

    cases = [
        ("replace", True),           # lowercase, contract says case-insensitive
        ("  ARRAY_APPEND  ", True),  # whitespace-trimmed
        ("array_remove", True),
        ("REPLACE", True),
        ("", False),                 # empty op
        ("Merge", False),            # unknown op
        ("UPSERT", False),
        ("ARRAY_APPENDX", False),
        ("REPLACE\r", True),         # trailing CR trim
    ]
    defects = []
    for op_val, expect_ok in cases:
        s, b, raw = safe_request("POST", "entities+upsert", {
            "collectionName": col,
            "data": [{"id": 1, "tags": ["x"]}],
            "partialUpdate": True,
            "fieldOps": [{"fieldName": "tags", "op": op_val}],
        })
        c = code_of(b)
        accepted = ok(b)
        print("op=%r -> code=%s raw=%s" % (op_val, c, raw[:200]))
        if expect_ok and not accepted:
            print("  NOTE: contract-accepted op form rejected (judge: doc-conformance)")
        if (not expect_ok) and accepted:
            defects.append("op=%r accepted (code 0) but contract requires 1100" % op_val)
        if (not expect_ok) and (not accepted) and c != 1100:
            print("  NOTE: rejected but code=%s != 1100 (Type2 candidate)" % c)

    try:
        drop_collection(col)
    except Exception:
        pass

    if defects:
        for d in defects:
            print("DEFECT: %s" % d)
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - invalid fieldOps op accepted")
    else:
        print("VERDICT: NO_DEFECT")

if __name__ == "__main__":
    main()
