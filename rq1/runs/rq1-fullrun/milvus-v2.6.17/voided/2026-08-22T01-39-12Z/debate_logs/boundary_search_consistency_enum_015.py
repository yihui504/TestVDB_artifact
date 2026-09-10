#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.17
Attack: boundary (enum/type) - entities+search consistencyLevel: valid Strong/Bounded, invalid 'strong' (case), '', 'Foo', null, int 1, nested dict; plus searchParams nprobe: -1, 0, 1e9, 'abc', ef negative
Constraint: milvus_type_entities_search_001
Source: .milvus-src-2617/internal/distributed/proxy/httpserver/handler_v2.go
Doc Version: v2.6.17
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import safe_request, code_of, drop_collection, create_collection, load_collection

def ok(b):
    return code_of(b) == 0

def main():
    col = "bnd_cons_015"
    drop_collection(col)
    s, b, raw = create_collection(col, with_array=False)
    if not ok(b):
        print("VERDICT: SCRIPT_ERROR - setup failed: %s" % raw[:300]); return
    load_collection(col)
    safe_request("POST", "entities+insert", {
        "collectionName": col, "data": [{"id": 1, "vector": [0.1] * 8}]})

    defects = []
    for label, cl, expect_ok in [
        ("Strong (valid)", "Strong", True),
        ("Bounded (valid)", "Bounded", True),
        ("strong lowercase", "strong", False),
        ("empty", "", False),
        ("Foo", "Foo", False),
        ("null", None, False),
        ("int 1", 1, False),
        ("nested dict", {"v": "Strong"}, False),
    ]:
        s, b, raw = safe_request("POST", "entities+search", {
            "collectionName": col, "data": [[0.1] * 8], "limit": 5, "consistencyLevel": cl})
        c = code_of(b)
        print("consistencyLevel=%r (%s) -> code=%s raw=%s" % (cl, label, c, raw[:200]))
        if expect_ok is False and ok(b):
            defects.append("consistencyLevel=%r accepted (code 0), contract requires 1100" % (cl,))
        if (not ok(b)) and c is not None and c != 1100:
            print("  NOTE: rejected code=%s != 1100 (Type2 candidate)" % c)

    # searchParams numeric boundaries (FLAT index: level consumed)
    for label, sp in [
        ("nprobe -1", {"nprobe": -1}),
        ("nprobe 0", {"nprobe": 0}),
        ("nprobe 1e9", {"nprobe": 1000000000}),
        ("nprobe abc", {"nprobe": "abc"}),
        ("nprobe null", {"nprobe": None}),
        ("ef -5", {"ef": -5}),
        ("level 99", {"level": 99}),
    ]:
        s, b, raw = safe_request("POST", "entities+search", {
            "collectionName": col, "data": [[0.1] * 8], "limit": 5, "searchParams": sp})
        c = code_of(b)
        print("searchParams %s -> code=%s raw=%s" % (label, c, raw[:180]))
        if s >= 500 or any(k in raw.lower() for k in ("panic", "internal error")):
            defects.append("searchParams %s -> 5xx/panic: %s" % (label, raw[:120]))

    try:
        drop_collection(col)
    except Exception:
        pass

    if defects:
        for d in defects:
            print("DEFECT: %s" % d)
        print("VERDICT: DEFECT_FOUND (Type1/Type3) - invalid consistencyLevel/searchParams accepted")
    else:
        print("VERDICT: NO_DEFECT")

if __name__ == "__main__":
    main()
