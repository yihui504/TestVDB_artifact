#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.17
Attack: boundary (header) - Request-Timeout header matrix: legal ints (1, 0, negative), huge (INT64_MAX, 1e19 overflow), unparseable ('abc', '', '1.5', ' 1 ', '+1', '0x10', unicode digits, NUL-embedded). Contract: ParseInt seconds; unparseable silently ignored; elapsed > effective timeout => HTTP 408
Constraint: milvus_type_request_timeout_001
Source: .milvus-src-2617/internal/distributed/proxy/httpserver/handler_v2.go (timeout middleware)
Doc Version: v2.6.17
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests
from _lib import safe_request, code_of, drop_collection, API, HEADERS
from _lib import create_collection, load_collection

def ok(b):
    return code_of(b) == 0

def req_with_header(path_key, payload, header_val, timeout=30):
    url = API + path_key.replace("+", "/")
    h = dict(HEADERS)
    h["Request-Timeout"] = header_val
    try:
        r = requests.post(url, headers=h, data=json.dumps(payload), timeout=timeout)
        try:
            body = r.json()
        except Exception:
            body = None
        return r.status_code, body, r.text
    except Exception as e:
        return -1, None, "EXC: %s" % e

def main():
    col = "bnd_reqtimeout_007"
    drop_collection(col)
    s, b, raw = create_collection(col, with_array=False)
    if not ok(b):
        print("VERDICT: SCRIPT_ERROR - setup failed: %s" % raw[:300]); return
    load_collection(col)
    payload = {"collectionName": col, "data": [{"id": 1, "vector": [0.1] * 8}]}

    cases = [
        ("1", "legal int"),
        ("0", "zero seconds"),
        ("-5", "negative"),
        ("9223372036854775807", "INT64_MAX"),
        ("9223372036854775808", "INT64_MAX+1 overflow"),
        ("99999999999999999999999", "way overflow"),
        ("abc", "unparseable"),
        ("", "empty"),
        ("1.5", "float"),
        (" 1 ", "spaces"),
        ("+1", "plus sign"),
        ("0x10", "hex"),
        ("１", "fullwidth digit"),
        ("1\x00", "NUL embedded"),
    ]
    defects = []
    for val, label in cases:
        t0 = time.time()
        s, b, raw = req_with_header("entities+insert", payload, val)
        el = time.time() - t0
        print("Request-Timeout=%r (%s) -> http=%s code=%s elapsed=%.2fs raw=%s"
              % (val, label, s, code_of(b), el, raw[:150]))
        if s >= 500:
            defects.append("header %r (%s) -> HTTP %s (5xx)" % (val, label, s))
        if s == 408 and el < 0.5 and val in ("1",):
            print("  NOTE: 408 returned before 1s could elapse (suspicious)")
        # unparseable should be ignored -> success
        if val in ("abc", "", "1.5", " 1 ", "+1", "0x10") and code_of(b) not in (0, None):
            print("  NOTE: unparseable header caused code=%s (contract says silently ignored)" % code_of(b))

    try:
        drop_collection(col)
    except Exception:
        pass

    if defects:
        for d in defects:
            print("DEFECT: %s" % d)
        print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - malformed Request-Timeout causes 5xx")
    else:
        print("VERDICT: NO_DEFECT")

if __name__ == "__main__":
    main()
