#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.17
Attack: boundary (zero-form) - partialUpdate type confusion: partialUpdate as string "true"/int 1/null; plus REPLACE with null value (should clear or reject, not corrupt); readback verification
Constraint: entities+upsert partialUpdate typing + milvus_state_entities_upsert_fieldops_001
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
        ], "enableDynamicField": True},
        "indexParams": [{"fieldName": "vec", "indexName": "vec_idx", "metricType": "L2"}],
    })
    if not ok(b):
        return s, b, raw
    s, b, raw = safe_request("POST", "collections+load", {"collectionName": col})
    if not ok(b):
        return s, b, raw
    return safe_request("POST", "entities+insert", {"collectionName": col, "data": [
        {"id": 1, "vec": [0.1] * 8, "title": "orig"},
    ]})

def main():
    col = "bnd_pu_zero_006"
    s, b, raw = setup_col(col)
    if not ok(b):
        print("VERDICT: SCRIPT_ERROR - setup failed: %s" % raw[:300]); return

    defects = []
    # type confusion on partialUpdate flag
    for pv in ("true", 1, None, "", "yes"):
        payload = {"collectionName": col, "data": [{"id": 1, "title": "pu_%r" % (pv,)}],
                   "partialUpdate": pv, "fieldOps": [{"fieldName": "title", "op": "REPLACE"}]}
        s, b, raw = safe_request("POST", "entities+upsert", payload)
        print("partialUpdate=%r -> code=%s raw=%s" % (pv, code_of(b), raw[:200]))

    # REPLACE with null value
    s, b, raw = safe_request("POST", "entities+upsert", {
        "collectionName": col, "data": [{"id": 1, "title": None}],
        "partialUpdate": True, "fieldOps": [{"fieldName": "title", "op": "REPLACE"}]})
    print("REPLACE null title -> code=%s raw=%s" % (code_of(b), raw[:200]))
    if ok(b):
        s2, b2, r2 = query_all(col, "id == 1", output_fields=["title"])
        rows = (b2 or {}).get("data") or []
        print("  readback title=%r" % (rows[0].get("title") if rows else "?",))

    # REPLACE with wrong-type value (int into VarChar)
    s, b, raw = safe_request("POST", "entities+upsert", {
        "collectionName": col, "data": [{"id": 1, "title": 12345}],
        "partialUpdate": True, "fieldOps": [{"fieldName": "title", "op": "REPLACE"}]})
    print("REPLACE int->VarChar -> code=%s raw=%s" % (code_of(b), raw[:200]))
    if ok(b):
        s2, b2, r2 = query_all(col, "id == 1", output_fields=["title"])
        rows = (b2 or {}).get("data") or []
        tb = rows[0].get("title") if rows else None
        print("  readback title=%r" % (tb,))
        if tb == 12345:
            defects.append("int value persisted into VarChar field without coercion")

    # missing data entirely with fieldOps
    s, b, raw = safe_request("POST", "entities+upsert", {
        "collectionName": col, "partialUpdate": True,
        "fieldOps": [{"fieldName": "title", "op": "REPLACE"}]})
    print("no data key -> code=%s raw=%s" % (code_of(b), raw[:200]))

    try:
        drop_collection(col)
    except Exception:
        pass

    if defects:
        for d in defects:
            print("DEFECT: %s" % d)
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)")
    else:
        print("VERDICT: NO_DEFECT")

if __name__ == "__main__":
    main()
