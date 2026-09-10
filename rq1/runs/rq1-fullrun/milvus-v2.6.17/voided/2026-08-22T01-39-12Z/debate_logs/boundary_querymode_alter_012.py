#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.17
Attack: boundary (enum) - collections+alter_properties query_mode values: 'large_topk' (valid), '', 'Large_TopK', 'largeTopk', 'foo', null, int; contract: invalid -> 65535 'invalid query_mode value ... valid values: [large_topk]'
Constraint: milvus_type_collections_create_009 + milvus_range_collections_querymode_001
Source: .milvus-src-2617/internal/distributed/proxy/httpserver/handler_v2.go + task.go
Doc Version: v2.6.17
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import safe_request, code_of, drop_collection

def ok(b):
    return code_of(b) == 0

def main():
    col = "bnd_qm_012"
    drop_collection(col)
    s, b, raw = safe_request("POST", "collections+create", {"collectionName": col, "dimension": 8})
    if not ok(b):
        print("VERDICT: SCRIPT_ERROR - setup failed: %s" % raw[:300]); return

    cases = [
        ("large_topk (valid)", "large_topk", None),
        ("empty", "", False),
        ("case variant Large_TopK", "Large_TopK", False),
        ("camel largeTopk", "largeTopk", False),
        ("foo", "foo", False),
        ("null", None, False),
        ("int 1", 1, False),
        ("large_topk with ws", " large_topk ", False),
    ]
    defects = []
    for label, val, expect_ok in cases:
        s, b, raw = safe_request("POST", "collections+alter_properties", {
            "collectionName": col,
            "properties": {"query_mode": val},
        })
        c = code_of(b)
        print("%s -> code=%s raw=%s" % (label, c, raw[:220]))
        if expect_ok is False and ok(b):
            defects.append("alter_properties query_mode=%r accepted (code 0), contract requires 65535" % val)
        if (not ok(b)) and c not in (65535, 702) and c is not None:
            print("  NOTE: rejected with code=%s (expected 65535 family; Type2 candidate)" % c)

    # also try alter query_mode with no value at all / missing key
    s, b, raw = safe_request("POST", "collections+alter_properties", {
        "collectionName": col, "properties": {}})
    print("empty properties -> code=%s raw=%s" % (code_of(b), raw[:180]))

    try:
        drop_collection(col)
    except Exception:
        pass

    if defects:
        for d in defects:
            print("DEFECT: %s" % d)
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - invalid query_mode accepted")
    else:
        print("VERDICT: NO_DEFECT")

if __name__ == "__main__":
    main()
