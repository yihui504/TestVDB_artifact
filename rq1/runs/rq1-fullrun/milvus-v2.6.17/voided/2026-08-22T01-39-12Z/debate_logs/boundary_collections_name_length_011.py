#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.17
Attack: boundary (range) - collection name length: 255 (max), 256 (max+1), 1000, empty, NUL-embedded, unicode; plus numShards: 0, -1, 17 (max+1); plus VarChar max_length 65536 (max+1) at schema level
Constraint: milvus_range_collections_create_002 + milvus_range_collections_create_005 + milvus_range_collections_create_004
Source: .milvus-src-2617/internal/distributed/proxy/httpserver/handler_v2.go (proxy.maxNameLength/maxShardNum/maxVarCharLength)
Doc Version: v2.6.17
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests
from _lib import safe_request, code_of, drop_collection, API, HEADERS

def ok(b):
    return code_of(b) == 0

def raw_create(body_str):
    url = API + "collections/create"
    try:
        r = requests.post(url, headers=HEADERS, data=body_str.encode("utf-8"), timeout=60)
        try:
            body = r.json()
        except Exception:
            body = None
        return r.status_code, body, r.text
    except Exception as e:
        return -1, None, "EXC: %s" % e

def main():
    defects = []
    # name length (quick mode)
    for label, name, expect_ok in [
        ("name len 255 (max)", "n" * 255, True),
        ("name len 256 (max+1)", "n" * 256, False),
        ("name len 1000", "n" * 1000, False),
        ("name empty", "", False),
        ("name NUL embedded", "ab" + chr(0) + "cd", False),
    ]:
        s, b, raw = raw_create(json.dumps({"collectionName": name, "dimension": 8}))
        c = code_of(b)
        print("%s -> code=%s raw=%s" % (label, c, raw[:160]))
        if expect_ok is False and ok(b):
            defects.append("create with %s accepted (code 0), contract: len<=255 / no NUL" % label)
        if expect_ok is True and not ok(b):
            print("  NOTE: max-length name rejected (judge candidate)")
        drop_collection(name)

    # numShards
    for label, shards in [("numShards 0", 0), ("numShards -1", -1), ("numShards 17 (max+1)", 17)]:
        col = "bnd_shards_%s" % abs(shards)
        drop_collection(col)
        s, b, raw = safe_request("POST", "collections+create",
                                 {"collectionName": col, "dimension": 8, "numShards": shards})
        print("%s -> code=%s raw=%s" % (label, code_of(b), raw[:160]))
        if ok(b):
            defects.append("create with %s accepted (code 0), contract: 1<=numShards<=16" % label)
        drop_collection(col)

    # VarChar max_length 65536 (max 65535)
    col = "bnd_vcmax_011"
    drop_collection(col)
    s, b, raw = safe_request("POST", "collections+create", {
        "collectionName": col,
        "schema": {"fields": [
            {"fieldName": "id", "dataType": "Int64", "isPrimary": True, "elementTypeParams": {}},
            {"fieldName": "vec", "dataType": "FloatVector", "elementTypeParams": {"dim": "8"}},
            {"fieldName": "t", "dataType": "VarChar", "elementTypeParams": {"max_length": "65536"}},
        ], "enableDynamicField": True},
    })
    print("VarChar max_length=65536 -> code=%s raw=%s" % (code_of(b), raw[:160]))
    if ok(b):
        defects.append("VarChar max_length=65536 accepted (contract max 65535)")
    # and negative max_length
    drop_collection(col)
    s, b, raw = safe_request("POST", "collections+create", {
        "collectionName": col,
        "schema": {"fields": [
            {"fieldName": "id", "dataType": "Int64", "isPrimary": True, "elementTypeParams": {}},
            {"fieldName": "vec", "dataType": "FloatVector", "elementTypeParams": {"dim": "8"}},
            {"fieldName": "t", "dataType": "VarChar", "elementTypeParams": {"max_length": "-1"}},
        ], "enableDynamicField": True},
    })
    print("VarChar max_length=-1 -> code=%s raw=%s" % (code_of(b), raw[:160]))
    if ok(b):
        defects.append("VarChar max_length=-1 accepted")
    drop_collection(col)

    if defects:
        for d in defects:
            print("DEFECT: %s" % d)
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - name/shards/varchar range violation accepted")
    else:
        print("VERDICT: NO_DEFECT")

if __name__ == "__main__":
    main()
