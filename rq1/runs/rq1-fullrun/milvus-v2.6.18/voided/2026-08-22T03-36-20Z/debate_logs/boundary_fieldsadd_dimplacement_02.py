#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.18
Attack: boundary (dim placement variant: top-level 'dimension' key on fields+add)
Constraint: milvus_type_collections_fields_add_001
Coverage: (fields+add vector dim placement) x {top-level dimension, string dim, dim=0, dim=-1}
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _milvus_helper import safe_request, code, drop

COLL = "b_fa_dim_02"

def add_field(schema):
    return safe_request("POST", "collections+fields+add",
                        {"collectionName": COLL, "schema": schema})

def readback_dim(name):
    _, b, raw = safe_request("POST", "collections+describe", {"collectionName": COLL})
    try:
        for f in b["data"]["schema"]["fields"]:
            if f.get("fieldName") == name:
                tp = f.get("typeParams") or f.get("elementTypeParams") or {}
                return tp.get("dim") or tp.get("dimension")
    except Exception:
        pass
    return None

def main():
    drop(COLL)
    st, b, raw = safe_request("POST", "collections+create", {
        "collectionName": COLL, "dimension": 8, "idType": "Int64",
        "vectorFieldName": "vec", "metricType": "COSINE"})
    if code(b) != 0:
        print("VERDICT: SCRIPT_ERROR — setup create failed:", raw[:200])
        return

    # Case 1: dim via TOP-LEVEL 'dimension' key instead of elementTypeParams.dim
    # contract: top-level dimension does not populate TypeParams -> reject or no dim
    st, b, raw = add_field({"fieldName": "vtop", "dataType": "FloatVector",
                            "nullable": True, "dimension": 16})
    print("add top-level dimension:", st, raw[:300])
    d = readback_dim("vtop")
    print("readback dim for vtop:", d)
    if code(b) == 0 and d in (None, "", "0"):
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — top-level dimension key accepted (code 0) but dim not persisted (%r): schema-inconsistent vector field" % d)
        return

    # Case 2: dim=0
    st, b, raw = add_field({"fieldName": "vzero", "dataType": "FloatVector",
                            "nullable": True, "elementTypeParams": {"dim": "0"}})
    print("add dim=0:", st, raw[:300])
    if code(b) == 0:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — dim=0 accepted for added vector field")
        return

    # Case 3: dim=-1
    st, b, raw = add_field({"fieldName": "vneg", "dataType": "FloatVector",
                            "nullable": True, "elementTypeParams": {"dim": "-1"}})
    print("add dim=-1:", st, raw[:300])
    if code(b) == 0:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — dim=-1 accepted for added vector field")
        return

    print("VERDICT: NO_DEFECT — dim placement/boundary values correctly handled")

if __name__ == "__main__":
    try:
        main()
    finally:
        drop(COLL)
