#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.17
Attack: boundary (zero-form/structural) - fieldOps on primary key field; empty fieldName; absent schema field; duplicate ops per field; fieldOps without partialUpdate; fieldOps with missing row in data. Contract: any structural violation -> 1100, no rows modified
Constraint: milvus_state_entities_upsert_fieldops_001
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
        {"id": 1, "vec": [0.1] * 8, "tags": ["a"], "title": "orig"},
    ]})

def main():
    col = "bnd_fieldops_pkstruct_005"
    s, b, raw = setup_col(col)
    if not ok(b):
        print("VERDICT: SCRIPT_ERROR - setup failed: %s" % raw[:300]); return

    cases = [
        ("op on pk field", {"data": [{"id": 99, "id": 1}], "fieldOps": [{"fieldName": "id", "op": "REPLACE"}]}, False),
        ("empty fieldName", {"data": [{"id": 1, "title": "x"}], "fieldOps": [{"fieldName": "", "op": "REPLACE"}]}, False),
        ("field absent from schema", {"data": [{"id": 1, "ghost": "x"}], "fieldOps": [{"fieldName": "ghost", "op": "REPLACE"}]}, False),
        ("duplicate ops same field", {"data": [{"id": 1, "title": "x"}],
         "fieldOps": [{"fieldName": "title", "op": "REPLACE"}, {"fieldName": "title", "op": "REPLACE"}]}, False),
        ("fieldOps no partialUpdate", {"data": [{"id": 1, "title": "x"}], "fieldOps": [{"fieldName": "title", "op": "REPLACE"}]}, None),
        ("row not in data", {"data": [{"id": 7, "title": "x"}], "fieldOps": [{"fieldName": "title", "op": "REPLACE"}]}, None),
        ("fieldOps empty array", {"data": [{"id": 1, "title": "x"}], "fieldOps": []}, None),
    ]
    defects = []
    for label, extra, must_fail in cases:
        payload = {"collectionName": col, "partialUpdate": True}
        payload.update(extra)
        s, b, raw = safe_request("POST", "entities+upsert", payload)
        print("%s -> code=%s raw=%s" % (label, code_of(b), raw[:220]))
        if must_fail is False and ok(b):
            defects.append("%s accepted (code 0), contract requires 1100" % label)
        # state check: original row must be intact after failed ops
        if not ok(b):
            s2, b2, r2 = query_all(col, "id == 1", output_fields=["title", "tags"])
            rows = (b2 or {}).get("data") or []
            if rows and rows[0].get("title") not in ("orig", None):
                defects.append("state leak: title changed to %r despite rejected op (%s)" % (rows[0].get("title"), label))

    try:
        drop_collection(col)
    except Exception:
        pass

    if defects:
        for d in defects:
            print("DEFECT: %s" % d)
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - fieldOps structural violation accepted")
    else:
        print("VERDICT: NO_DEFECT")

if __name__ == "__main__":
    main()
