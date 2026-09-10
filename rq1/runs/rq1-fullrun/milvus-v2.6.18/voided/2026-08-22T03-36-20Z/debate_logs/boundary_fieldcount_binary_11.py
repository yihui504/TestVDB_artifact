#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.18
Attack: boundary (max fields 64 / max vector fields 4 / BinaryVector dim %8)
Constraint: milvus_range_collections_create_003, milvus_type_collections_create_005
Coverage: (numFields) x {64, 65}; (numVectorFields) x {4, 5}; (BinaryVector dim) x {8, 9}
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _milvus_helper import safe_request, code, drop

def fields_create(coll, fields):
    return safe_request("POST", "collections+create", {
        "collectionName": coll,
        "schema": {"autoId": False, "fields": fields}})

def main():
    # --- max fields: 64 ok, 65 reject
    f64 = [{"fieldName": "id", "dataType": "Int64", "isPrimary": True},
           {"fieldName": "v1", "dataType": "FloatVector", "elementTypeParams": {"dim": "4"}}]
    f64 += [{"fieldName": "s%d" % i, "dataType": "Int32"} for i in range(62)]  # total 64
    st, b, raw = fields_create("b_fc_64", f64)
    print("fields=64:", raw[:150])
    if code(b) != 0:
        print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — 64 fields rejected: %s" % raw[:200]); return
    f65 = f64 + [{"fieldName": "sX", "dataType": "Int32"}]
    st, b, raw = fields_create("b_fc_65", f65)
    print("fields=65:", raw[:200])
    if code(b) == 0:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — 65 fields accepted, max 64"); return

    # --- max vector fields: 4 ok, 5 reject
    f4 = [{"fieldName": "id", "dataType": "Int64", "isPrimary": True}] + [
        {"fieldName": "vv%d" % i, "dataType": "FloatVector", "elementTypeParams": {"dim": "4"}}
        for i in range(4)]
    st, b, raw = fields_create("b_vf_4", f4)
    print("vectorFields=4:", raw[:150])
    f5 = f4 + [{"fieldName": "vvX", "dataType": "FloatVector", "elementTypeParams": {"dim": "4"}}]
    st, b, raw = fields_create("b_vf_5", f5)
    _, bb, _ = safe_request("POST", "collections+describe", {"collectionName": "b_vf_5"})
    nvec = len([fd for fd in (bb["data"]["fields"]) if "Vector" in fd.get("type", "")]) if bb else None
    print("vectorFields=5:", raw[:200], "persisted vec fields:", nvec)
    if code(b) == 0 and nvec == 5:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — 5 vector fields accepted and persisted, max 4"); return

    # --- BinaryVector dim multiple of 8
    b8 = [{"fieldName": "id", "dataType": "Int64", "isPrimary": True},
          {"fieldName": "bv", "dataType": "BinaryVector", "elementTypeParams": {"dim": "8"}}]
    st, b, raw = fields_create("b_bin_8", b8)
    print("bin dim=8:", raw[:150])
    if code(b) != 0:
        print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — BinaryVector dim=8 rejected: %s" % raw[:200]); return
    b9 = [{"fieldName": "id", "dataType": "Int64", "isPrimary": True},
          {"fieldName": "bv", "dataType": "BinaryVector", "elementTypeParams": {"dim": "9"}}]
    st, b, raw = fields_create("b_bin_9", b9)
    print("bin dim=9:", raw[:200])
    if code(b) == 0:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — BinaryVector dim=9 (not %8) accepted"); return

    print("VERDICT: NO_DEFECT — field count / vector field count / binary dim bounds enforced")

if __name__ == "__main__":
    try:
        main()
    finally:
        for n in ("b_fc_64", "b_fc_65", "b_vf_4", "b_vf_5", "b_bin_8", "b_bin_9"):
            drop(n)
