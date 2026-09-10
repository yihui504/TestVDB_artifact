#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.18
Attack: boundary (2.6.18 new face: collections/fields/add vector field)
Constraint: milvus_type_collections_fields_add_001
Coverage: (fields+add vector) x {nullable+dim happy, non-nullable, missing dim, top-level dimension key}
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _milvus_helper import safe_request, code, drop

COLL = "b_fa_vec_01"

def add_field(schema):
    return safe_request("POST", "collections+fields+add",
                        {"collectionName": COLL, "schema": schema})

def describe_fields():
    _, b, raw = safe_request("POST", "collections+describe", {"collectionName": COLL})
    try:
        return [f for f in b["data"]["fields"] if f.get("name") == "vfa"], raw
    except Exception:
        return None, raw

def main():
    drop(COLL)
    st, b, raw = safe_request("POST", "collections+create", {
        "collectionName": COLL, "dimension": 8,
        "primaryFieldName": "id", "idType": "Int64", "vectorFieldName": "vec",
        "metricType": "COSINE"})
    print("create:", st, raw[:200])
    if code(b) != 0:
        print("VERDICT: SCRIPT_ERROR — setup create failed")
        return
    results = []

    # Case 1: happy path nullable vector + elementTypeParams.dim
    st, b, raw = add_field({"fieldName": "vfa", "dataType": "FloatVector",
                            "nullable": True,
                            "elementTypeParams": {"dim": "16"}})
    print("add nullable+dim:", st, raw[:300])
    fields, draw = describe_fields()
    persisted_dim = None
    if fields:
        tp = {p.get("key"): p.get("value") for p in (fields[0].get("params") or [])}
        persisted_dim = tp.get("dim")
    print("describe readback field:", fields, "dim=", persisted_dim)
    # Expect: code 0 AND dim persisted as 16. code 0 but dim missing/dropped -> Type1 candidate
    if code(b) == 0 and persisted_dim not in ("16", 16):
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — fields+add vector accepted (code 0) but dim NOT persisted in schema (readback=%r)" % persisted_dim)
        return
    results.append(("nullable+dim", code(b)))

    # Case 2: non-nullable vector -> expect 1100
    st, b, raw = add_field({"fieldName": "vfb", "dataType": "FloatVector",
                            "elementTypeParams": {"dim": "8"}})
    print("add non-nullable:", st, raw[:300])
    if code(b) == 0:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — non-nullable vector field accepted, expected 1100")
        return

    # Case 3: nullable vector missing dim entirely -> expect 1100
    st, b, raw = add_field({"fieldName": "vfc", "dataType": "FloatVector", "nullable": True})
    print("add missing dim:", st, raw[:300])
    if code(b) == 0:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — nullable vector field without dim accepted, expected 1100")
        return

    # Type-2: error should mention nullable or dimension
    if "dim" not in raw.lower() and "null" not in raw.lower():
        print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — error message lacks dim/nullable hint: %s" % raw[:200])
        return

    print("VERDICT: NO_DEFECT — nullable+dim accepted+persisted; non-nullable & missing-dim correctly rejected 1100")

if __name__ == "__main__":
    try:
        main()
    finally:
        drop(COLL)
