#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.17
Attack: type boundary - users+create password/userName type confusion: int, list, dict, null, missing key; and update_password with bad oldPassword/newPassword forms; NUL byte in password
Constraint: milvus_range_users_create_001 (typing family) + users+update_password
Source: .milvus-src-2617/internal/distributed/proxy/httpserver/handler_v2.go
Doc Version: v2.6.17
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests
from _lib import safe_request, code_of, API, HEADERS

def ok(b):
    return code_of(b) == 0

def raw_post(path_key, body_str, timeout=30):
    url = API + path_key.replace("+", "/")
    try:
        r = requests.post(url, headers=HEADERS, data=body_str.encode("utf-8"), timeout=timeout)
        try:
            body = r.json()
        except Exception:
            body = None
        return r.status_code, body, r.text
    except Exception as e:
        return -1, None, "EXC: %s" % e

def main():
    defects = []
    cases = [
        ("password int", '{"userName":"bndty1","password":123456}'),
        ("password list", '{"userName":"bndty2","password":["a","b"]}'),
        ("password dict", '{"userName":"bndty3","password":{"v":"abc"}}'),
        ("password null", '{"userName":"bndty4","password":null}'),
        ("password missing", '{"userName":"bndty5"}'),
        ("userName int", '{"userName":42,"password":"123456"}'),
        ("userName null", '{"userName":null,"password":"123456"}'),
        ("userName missing", '{"password":"123456"}'),
    ]
    for label, body in cases:
        s, b, raw = raw_post("users+create", body)
        c = code_of(b)
        print("%s -> http=%s code=%s raw=%s" % (label, s, c, raw[:180]))
        if s >= 500:
            defects.append("%s -> HTTP %s 5xx on mistyped body" % (label, s))
        if ok(b):
            defects.append("%s accepted (code 0) with mistyped/missing field" % label)

    # NUL byte in password (raw body, valid-length otherwise)
    s, b, raw = raw_post("users+create", '{"userName":"bndty9","password":"ab\\u0000cdef"}')
    print("password NUL -> http=%s code=%s raw=%s" % (s, code_of(b), raw[:180]))
    if s >= 500 or "panic" in raw.lower() or "internal" in raw.lower():
        defects.append("NUL password -> http=%s raw leaks internal error" % s)

    # update_password with wrong-typed fields
    s, b, raw = raw_post("users+update_password",
                         '{"userName":"root","oldPassword":123,"newPassword":null}')
    print("update_password mistyped -> http=%s code=%s raw=%s" % (s, code_of(b), raw[:180]))
    if s >= 500:
        defects.append("update_password mistyped -> HTTP %s" % s)

    for u in ["bndty1", "bndty2", "bndty3", "bndty4", "bndty5", "bndty9"]:
        try:
            safe_request("POST", "users+drop", {"userName": u})
        except Exception:
            pass

    if defects:
        for d in defects:
            print("DEFECT: %s" % d)
        print("VERDICT: DEFECT_FOUND (Type1/Type3)")
    else:
        print("VERDICT: NO_DEFECT")

if __name__ == "__main__":
    main()
