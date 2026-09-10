#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.17
Attack: boundary (range) - ARRAY_APPEND beyond Array max_capacity: cap=4, seed 3 elems, append 2 (total 5 > cap); expect rejection (overflow guard); accept+persisted = Type1; also boundary append reaching exactly cap (4) = legal
Constraint: milvus_type_entities_upsert_fieldops_002 + Array elementDataType max_capacity range family
Source: .milvus-src-2617/internal/distributed/proxy/httpserver/handler_v2.go
Doc Version: v2.6.17
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import safe_request, code_of, drop_collection, query_all

def ok(b):
    return code_of(b) == 0

def setup_col(col, cap):
    drop_collection(col)
    s, b, raw = safe_request("POST", "collections+create", {
        "collectionName": col,
        "schema": {"fields": [
            {"fieldName": "id", "dataType": "Int64", "isPrimary": True, "elementTypeParams": {}},
            {"fieldName": "vec", "dataType": "FloatVector", "elementTypeParams": {"dim": "8"}},
            {"fieldName": "tags", "dataType": "Array", "elementDataType": "VarChar",
             "elementTypeParams": {"max_capacity": str(cap), "max_length": "64"}},
        ], "enableDynamicField": True},
        "indexParams": [{"fieldName": "vec", "indexName": "vec_idx", "metricType": "L2"}],
    })
    if not ok(b):
        return s, b, raw
    s, b, raw = safe_request("POST", "collections+load", {"collectionName": col})
    if not ok(b):
        return s, b, raw
    return safe_request("POST", "entities+insert", {"collectionName": col, "data": [
        {"id": 1, "vec": [0.1] * 8, "tags": ["e0", "e1", "e2"]},
    ]})

def main():
    col = "bnd_fieldops_cap_003"
    s, b, raw = setup_col(col, 4)
    if not ok(b):
        print("VERDICT: SCRIPT_ERROR - setup failed: %s" % raw[:300]); return

    defects = []

    # Case A: append exactly to cap (3+1=4) - legal per contract
    s, b, raw = safe_request("POST", "entities+upsert", {
        "collectionName": col,
        "data": [{"id": 1, "tags": ["e3"]}],
        "partialUpdate": True,
        "fieldOps": [{"fieldName": "tags", "op": "ARRAY_APPEND"}],
    })
    print("append to exactly cap=4 -> code=%s raw=%s" % (code_of(b), raw[:200]))

    # reset to 3 elems via REPLACE
    s, b, raw = safe_request("POST", "entities+upsert", {
        "collectionName": col,
        "data": [{"id": 1, "tags": ["e0", "e1", "e2"]}],
        "partialUpdate": True,
        "fieldOps": [{"fieldName": "tags", "op": "REPLACE"}],
    })
    if not ok(b):
        print("VERDICT: SCRIPT_ERROR - reset REPLACE failed: %s" % raw[:200]); return

    # Case B: append 2 (3+2=5 > cap=4) - overflow, expect rejection
    s, b, raw = safe_request("POST", "entities+upsert", {
        "collectionName": col,
        "data": [{"id": 1, "tags": ["e3", "e4"]}],
        "partialUpdate": True,
        "fieldOps": [{"fieldName": "tags", "op": "ARRAY_APPEND"}],
    })
    print("append overflow 5>cap4 -> code=%s raw=%s" % (code_of(b), raw[:250]))
    if ok(b):
        s2, b2, r2 = query_all(col, "id == 1", output_fields=["tags"])
        rows = (b2 or {}).get("data") or []
        stored = rows[0].get("tags") if rows else None
        print("  readback tags=%r (len=%s)" % (stored, len(stored) if isinstance(stored, list) else "?"))
        if isinstance(stored, list) and len(stored) > 4:
            defects.append("ARRAY_APPEND overflow accepted and PERSISTED len=%d > max_capacity=4" % len(stored))
        else:
            print("  NOTE: overflow accepted (code 0) but readback len<=4 (silent clamp/ignore - judge candidate)")

    # Case C: huge append (3+2000 > cap) - resource/DoS flavor of same bound
    s, b, raw = safe_request("POST", "entities+upsert", {
        "collectionName": col,
        "data": [{"id": 1, "tags": ["x"] * 2000}],
        "partialUpdate": True,
        "fieldOps": [{"fieldName": "tags", "op": "ARRAY_APPEND"}],
    })
    print("append 2000 elems -> code=%s raw=%s" % (code_of(b), raw[:250]))
    if code_of(b) in (1, 3) or "panic" in raw.lower() or "internal" in raw.lower():
        defects.append("append 2000 elems -> code=%s (server error/panic)" % code_of(b))

    try:
        drop_collection(col)
    except Exception:
        pass

    if defects:
        for d in defects:
            print("DEFECT: %s" % d)
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - ARRAY_APPEND max_capacity overflow accepted")
    else:
        print("VERDICT: NO_DEFECT")

if __name__ == "__main__":
    main()
