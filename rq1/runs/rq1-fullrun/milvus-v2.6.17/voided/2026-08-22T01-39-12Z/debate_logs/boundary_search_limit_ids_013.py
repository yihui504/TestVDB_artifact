#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.17
Attack: boundary (range+form) - entities+search limit: 0, -1, 16384 (max), 16385 (max+1); offset+limit window overflow; ids+data mutual exclusion (both / neither / ids=[]); ids fractional int64 pk 1.5 / empty VarChar pk
Constraint: milvus_range_entities_search_001/002/003 + milvus_type_entities_search_002/003
Source: .milvus-src-2617/internal/distributed/proxy/httpserver/handler_v2.go + quota_param.go
Doc Version: v2.6.17
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import safe_request, code_of, drop_collection, create_collection, load_collection

def ok(b):
    return code_of(b) == 0

def main():
    col = "bnd_search_lim_013"
    drop_collection(col)
    s, b, raw = create_collection(col, with_array=False)
    if not ok(b):
        print("VERDICT: SCRIPT_ERROR - setup failed: %s" % raw[:300]); return
    load_collection(col)
    s, b, raw = safe_request("POST", "entities+insert", {
        "collectionName": col, "data": [{"id": 1, "vector": [0.1] * 8},
                                        {"id": 2, "vector": [0.2] * 8}]})
    if not ok(b):
        print("VERDICT: SCRIPT_ERROR - seed failed: %s" % raw[:300]); return

    defects = []
    vec = {"data": [[0.1] * 8]}

    for label, extra, expect_ok in [
        ("limit 0", {"limit": 0}, False),
        ("limit -1", {"limit": -1}, False),
        ("limit 16385 (max+1)", {"limit": 16385}, False),
        ("limit '10' string", {"limit": "10"}, False),
        ("limit null", {"limit": None}, False),
        ("offset -1", {"offset": -1, "limit": 10}, False),
        ("offset+limit 16385 (window)", {"offset": 16380, "limit": 10}, False),
    ]:
        payload = {"collectionName": col, "data": [[0.1] * 8]}
        payload.update(extra)
        s, b, raw = safe_request("POST", "entities+search", payload)
        c = code_of(b)
        print("%s -> code=%s raw=%s" % (label, c, raw[:200]))
        if expect_ok is False and ok(b):
            defects.append("search %s accepted (code 0), contract requires 65535" % label)
        if (not ok(b)) and c is not None and c not in (65535, 1100, 1802):
            print("  NOTE: code=%s (expected 65535/1100; Type2 candidate)" % c)

    # ids/data mutual exclusion (int64 pk)
    for label, payload, expect_code in [
        ("both ids+data", {"ids": [1], "data": [[0.1] * 8]}, 1100),
        ("neither", {}, 1802),
        ("ids empty list", {"ids": []}, 1802),
        ("ids fractional 1.5", {"ids": [1.5]}, 1100),
        ("ids string '1'", {"ids": ["1"]}, 1100),
        ("ids null elem", {"ids": [None]}, 1100),
    ]:
        payload["collectionName"] = col
        s, b, raw = safe_request("POST", "entities+search", payload)
        c = code_of(b)
        print("%s -> code=%s raw=%s" % (label, c, raw[:200]))
        if c != expect_code:
            defects.append("%s -> code=%s, contract expects %s" % (label, c, expect_code))

    try:
        drop_collection(col)
    except Exception:
        pass

    if defects:
        for d in defects:
            print("DEFECT: %s" % d)
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - search boundary violation accepted")
    else:
        print("VERDICT: NO_DEFECT")

if __name__ == "__main__":
    main()
