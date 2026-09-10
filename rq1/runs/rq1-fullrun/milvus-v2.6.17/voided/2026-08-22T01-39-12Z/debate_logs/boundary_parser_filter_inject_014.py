#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.17
Attack: boundary (fuzz/malformed) - filter expression grammar: empty, NUL byte, lone UTF-16 surrogate, unbalanced parens, injection ('id == 1 or true'), deeply nested (500), overlong (100KB); plus malformed raw JSON body on entities+query. Expect 4xx-family code (1100 etc), NOT 5xx/panic
Constraint: milvus_type_entities_delete_001 (filter boolean expr) + parser grammar generalization
Source: .milvus-src-2617/internal/distributed/proxy/httpserver/handler_v2.go + pkg/parser
Doc Version: v2.6.17
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests
from _lib import safe_request, code_of, drop_collection, create_collection, load_collection, API, HEADERS

def ok(b):
    return code_of(b) == 0

def raw_post(path_key, body_bytes, timeout=60):
    url = API + path_key.replace("+", "/")
    try:
        r = requests.post(url, headers=HEADERS, data=body_bytes, timeout=timeout)
        try:
            body = r.json()
        except Exception:
            body = None
        return r.status_code, body, r.text
    except Exception as e:
        return -1, None, "EXC: %s" % e

def main():
    col = "bnd_parser_014"
    drop_collection(col)
    s, b, raw = create_collection(col, with_array=False)
    if not ok(b):
        print("VERDICT: SCRIPT_ERROR - setup failed: %s" % raw[:300]); return
    load_collection(col)
    safe_request("POST", "entities+insert", {
        "collectionName": col, "data": [{"id": 1, "vector": [0.1] * 8}]})

    defects = []
    filters = [
        ("empty filter", ""),
        ("NUL in filter", "id \x00== 1"),
        ("lone surrogate", u"id == '\ud800'"),
        ("unbalanced parens", "((id == 1)"),
        ("or-true injection", "id == 1 or true"),
        ("comment", "id == 1 // comment"),
        ("deep nesting 500", "(" * 500 + "id == 1" + ")" * 500),
        ("overlong 100KB", "id == 1 and " * 12000 + "id == 1"),
    ]
    for label, f in filters:
        s, b, raw = safe_request("POST", "entities+query", {
            "collectionName": col, "filter": f, "limit": 10})
        c = code_of(b)
        print("%s -> http=%s code=%s raw=%s" % (label, s, c, raw[:180]))
        if s >= 500 or any(k in raw.lower() for k in ("panic", "internal error", "runtime error")):
            defects.append("filter %r -> http=%s raw=%s (5xx/panic)" % (label, s, raw[:100]))

    # malformed raw JSON bodies
    bodies = [
        ("truncated json", b'{"collectionName": "%s", "filter": "id == 1' % col.encode()),
        ("trailing comma", b'{"collectionName": "%s", "filter": "id == 1",}' % col.encode()),
        ("single quotes", b"{'collectionName': '%s'}" % col.encode()),
        ("lone surrogate in name", ('{"collectionName": "%s", "note": "\\ud800"}' % col).encode()),
        ("NUL in body", b'{"collectionName": "%s", "filter": "id\x00 == 1"}' % col.encode()),
        ("bad escape", b'{"collectionName": "%s", "filter": "id \\q== 1"}' % col.encode()),
    ]
    for label, body in bodies:
        s, b, raw = raw_post("entities+query", body)
        print("[malformed] %s -> http=%s code=%s raw=%s" % (label, s, code_of(b), raw[:150]))
        if s >= 500:
            defects.append("malformed body %r -> HTTP %s" % (label, s))

    try:
        drop_collection(col)
    except Exception:
        pass

    if defects:
        for d in defects:
            print("DEFECT: %s" % d)
        print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - malformed input causes 5xx/panic")
    else:
        print("VERDICT: NO_DEFECT")

if __name__ == "__main__":
    main()
