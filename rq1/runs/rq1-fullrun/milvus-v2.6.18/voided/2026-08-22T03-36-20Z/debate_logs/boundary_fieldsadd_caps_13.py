#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.18
Attack: boundary (fields+add: vector field count cap 4 + normal-mode search limit boundary)
Constraint: milvus_range_collections_fields_add_001, milvus_range_entities_search_001
Coverage: (fields+add vec) x {5th vector field}; (search limit normal mode) x {16384, 16385, 20000}
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _milvus_helper import safe_request, code, drop

C = "b_fac_13"

def add_field(name):
    return safe_request("POST", "collections+fields+add", {
        "collectionName": C, "schema": {"fieldName": name, "dataType": "FloatVector",
                                        "nullable": True,
                                        "elementTypeParams": {"dim": "4"}}})

def main():
    drop(C)
    # create with 4 vector fields
    st, b, raw = safe_request("POST", "collections+create", {
        "collectionName": C,
        "schema": {"fields": [{"fieldName": "id", "dataType": "Int64", "isPrimary": True}] + [
            {"fieldName": "v%d" % i, "dataType": "FloatVector", "elementTypeParams": {"dim": "4"}}
            for i in range(4)]}})
    if code(b) != 0:
        print("VERDICT: SCRIPT_ERROR — setup create failed:", raw[:200]); return

    # adding the 5th vector field must be rejected (vectorFields(existing)+1 <= 4)
    st, b, raw = add_field("vadd")
    print("add 5th vector field:", raw[:250])
    if code(b) == 0:
        _, bb, _ = safe_request("POST", "collections+describe", {"collectionName": C})
        nvec = len([f for f in bb["data"]["fields"] if "Vector" in f.get("type", "")]) if bb else None
        print("persisted vector fields:", nvec)
        if nvec and nvec > 4:
            print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — 5th vector field added+persisted (cap 4)"); return
        print("OBSERVE: add returned 0 but readback shows %s vector fields" % nvec)

    # normal-mode search limit boundary: 16384 ok, 16385/20000 -> 65535
    # (defect above already returned; remaining checks recorded for completeness)
    safe_request("POST", "indexes+create", {"collectionName": C, "indexParams": [
        {"fieldName": "v%d" % i, "indexName": "i%d" % i, "metricType": "COSINE"} for i in range(4)]})
    safe_request("POST", "collections+load", {"collectionName": C})
    for lim in (16384, 16385, 20000):
        st, b, raw = safe_request("POST", "entities+search", {
            "collectionName": C, "data": [[0.1] * 4], "annsField": "v0", "limit": lim})
        print("limit=%d:" % lim, raw[:150])
        if lim == 16384 and code(b) != 0:
            print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — limit=16384 (documented max) rejected: %s" % raw[:200]); return
        if lim > 16384 and code(b) == 0:
            print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — limit=%d accepted in normal mode (max 16384)" % lim); return

    print("VERDICT: NO_DEFECT — fields+add vector cap + normal-mode limit bounds enforced")

if __name__ == "__main__":
    try:
        main()
    finally:
        drop(C)
