#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.17
Attack: boundary (string form) - field-name rules on insert: leading digit '1abc', 'a-b', 'a.b', NUL 'a\\u0000b', overlong 256, valid 255 and 1-char; dynamic-field path; empty string
Constraint: milvus_type_field_name_rules_001
Source: .milvus-src-2617 (official limitations.md naming rules; insert-time enforcement)
Doc Version: v2.6.17
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests
from _lib import safe_request, code_of, drop_collection, create_collection, load_collection, API, HEADERS

def ok(b):
    return code_of(b) == 0

def raw_insert(col, body_bytes, timeout=60):
    url = API + "entities/insert"
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
    col = "bnd_fname_018"
    drop_collection(col)
    s, b, raw = create_collection(col, with_array=False)  # dynamic fields enabled
    if not ok(b):
        print("VERDICT: SCRIPT_ERROR - setup failed: %s" % raw[:300]); return
    load_collection(col)

    defects = []
    dyn_names = [
        ("leading digit", "1abc"),
        ("hyphen", "a-b"),
        ("dot", "a.b"),
        ("dollar", "$x"),
        ("space", "a b"),
        ("empty", ""),
        ("overlong 256", "f" * 256),
        ("valid 255", "f" * 255),
        ("valid 1char", "x"),
        ("valid underscore", "_ok"),
    ]
    for label, name in dyn_names:
        body = json.dumps({"collectionName": col,
                           "data": [{"id": 1, "vector": [0.1] * 8, name: 5}]})
        s, b, raw = raw_insert(col, body.encode("utf-8"))
        print("dyn field %r (%s) -> http=%s code=%s raw=%s" % (name[:30], label, s, code_of(b), raw[:150]))
        if s >= 500:
            defects.append("dyn field %r -> HTTP %s" % (name[:30], s))
        if label.startswith("valid") and not ok(b):
            print("  NOTE: valid field name rejected (judge candidate)")
        if (not label.startswith("valid")) and ok(b):
            defects.append("illegal dynamic field name %r accepted (code 0)" % (name[:30],))

    # NUL byte via unicode escape in raw JSON
    body = ('{"collectionName": "%s", "data": [{"id": 2, "vector": [0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1], "a\\u0000b": 1}]}' % col).encode()
    s, b, raw = raw_insert(col, body)
    print("NUL dyn field -> http=%s code=%s raw=%s" % (s, code_of(b), raw[:150]))
    if s >= 500 or "panic" in raw.lower():
        defects.append("NUL dyn field -> http=%s raw=%s" % (s, raw[:100]))

    try:
        drop_collection(col)
    except Exception:
        pass

    if defects:
        for d in defects:
            print("DEFECT: %s" % d)
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - illegal field name accepted")
    else:
        print("VERDICT: NO_DEFECT")

if __name__ == "__main__":
    main()
