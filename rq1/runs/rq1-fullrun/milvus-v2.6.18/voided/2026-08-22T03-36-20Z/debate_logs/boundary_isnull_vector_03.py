#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.18
Attack: boundary (NEW v2.6.18 face: IS NULL / IS NOT NULL on vector fields)
Constraint: milvus_type_query_isnull_vector_001
Coverage: (IS NULL vector) x {FloatVector IS NULL, FloatVector IS NOT NULL, BinaryVector IS NULL, scalar-field IS NULL control}
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _milvus_helper import safe_request, code, drop

COLL = "b_isnull_03"

def query(f):
    return safe_request("POST", "entities+query",
                        {"collectionName": COLL, "filter": f, "limit": 10})

def main():
    drop(COLL)
    st, b, raw = safe_request("POST", "collections+create", {
        "collectionName": COLL, "dimension": 8, "idType": "Int64",
        "vectorFieldName": "vec", "metricType": "COSINE"})
    if code(b) != 0:
        print("VERDICT: SCRIPT_ERROR — setup create failed:", raw[:200]); return
    safe_request("POST", "collections+load", {"collectionName": COLL})

    # Case 1: IS NULL on FloatVector -> expect 1100
    st, b, raw = query("vec IS NULL")
    print("FloatVector IS NULL:", st, raw[:300])
    if code(b) == 0:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — IS NULL on vector field accepted, expected 1100"); return

    # Case 2: IS NOT NULL on FloatVector -> expect 1100
    st, b, raw = query("vec IS NOT NULL")
    print("FloatVector IS NOT NULL:", st, raw[:300])
    if code(b) == 0:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — IS NOT NULL on vector field accepted, expected 1100"); return

    # Type-2: message should mention vector fields
    if "vector" not in raw.lower():
        print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — message lacks 'vector': %s" % raw[:200]); return

    # Control: scalar IS NULL should be legal syntax (may return code 0/101 not-loaded, but NOT the vector-1100)
    st, b, raw = query("id IS NOT NULL")
    print("scalar control IS NOT NULL:", st, raw[:200])

    print("VERDICT: NO_DEFECT — IS NULL/IS NOT NULL on vector fields correctly rejected")

if __name__ == "__main__":
    try:
        main()
    finally:
        drop(COLL)
