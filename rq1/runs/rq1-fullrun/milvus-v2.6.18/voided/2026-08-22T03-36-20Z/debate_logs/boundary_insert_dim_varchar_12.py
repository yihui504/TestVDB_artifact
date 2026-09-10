#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.18
Attack: boundary (insert dim mismatch + VarChar max_length 65535)
Constraint: milvus_type_entities_insert_001, milvus_range_collections_create_004
Coverage: (insert vector dim) x {8 ok, 7, 9, 0, null}; (VarChar value len) x {65535, 65536}
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _milvus_helper import safe_request, code, drop

def main():
    # --- insert dim mismatch (quick create dim=8)
    C = "b_idm_12"
    drop(C)
    st, b, raw = safe_request("POST", "collections+create", {
        "collectionName": C, "dimension": 8, "idType": "Int64",
        "vectorFieldName": "vec", "metricType": "COSINE"})
    if code(b) != 0:
        print("VERDICT: SCRIPT_ERROR — setup create failed:", raw[:200]); return
    for dim, vec in [("7", [0.1] * 7), ("9", [0.1] * 9), ("0", [])]:
        st, b, raw = safe_request("POST", "entities+insert", {
            "collectionName": C, "data": [{"id": 1, "vec": vec}]})
        print("insert dim=%s:" % dim, raw[:180])
        if code(b) == 0:
            print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — insert with dim=%s into dim=8 collection accepted" % dim); return
    st, b, raw = safe_request("POST", "entities+insert", {
        "collectionName": C, "data": [{"id": 1, "vec": None}]})
    print("insert vec=null:", raw[:180])
    if code(b) == 0:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — insert with vec=null into non-nullable field accepted"); return
    # control: correct dim ok
    st, b, raw = safe_request("POST", "entities+insert", {
        "collectionName": C, "data": [{"id": 1, "vec": [0.1] * 8}]})
    print("insert dim=8 control:", raw[:120])
    if code(b) != 0:
        print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — correct-dim insert failed: %s" % raw[:200]); return

    # --- VarChar max_length boundary
    V = "b_vc_12"
    drop(V)
    st, b, raw = safe_request("POST", "collections+create", {
        "collectionName": V,
        "schema": {"fields": [
            {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
            {"fieldName": "vec", "dataType": "FloatVector", "elementTypeParams": {"dim": "4"}},
            {"fieldName": "s", "dataType": "VarChar", "elementTypeParams": {"max_length": "65535"}}]}})
    if code(b) != 0:
        print("VERDICT: SCRIPT_ERROR — varchar create failed:", raw[:200]); return
    st, b, raw = safe_request("POST", "entities+insert", {
        "collectionName": V, "data": [{"id": 1, "vec": [0.1] * 4, "s": "a" * 65534}]})
    print("varchar 65534:", raw[:150])
    if code(b) != 0:
        print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — 65534-char value rejected under max_length 65535: %s" % raw[:200]); return
    st, b, raw = safe_request("POST", "entities+insert", {
        "collectionName": V, "data": [{"id": 2, "vec": [0.1] * 4, "s": "a" * 65536}]})
    print("varchar 65536:", raw[:200])
    if code(b) == 0:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — 65536-char value accepted under max_length 65535"); return

    print("VERDICT: NO_DEFECT — insert dim + VarChar length bounds enforced")

if __name__ == "__main__":
    try:
        main()
    finally:
        drop("b_idm_12")
        drop("b_vc_12")
