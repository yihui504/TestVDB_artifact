#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.17
Attack: boundary (range) - users+create password length: 0/5 (below min 6), 6 (min), 72 (max), 73 (max+1), 1000 (way over); username length: 32 (max), 33 (max+1), empty, unicode. Contract: 6<=len<=72 else 1100 'out of range 6 <= value <= 72'; username <= 32
Constraint: milvus_range_users_create_001 + milvus_range_users_create_password_002
Source: .milvus-src-2617/internal/distributed/proxy/httpserver/handler_v2.go (proxy.minPasswordLength/bcrypt 72)
Doc Version: v2.6.17
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import safe_request, code_of

def ok(b):
    return code_of(b) == 0

def drop_user(u):
    try:
        safe_request("POST", "users+drop", {"userName": u})
    except Exception:
        pass

def main():
    base = "bndpw"
    defects = []
    cases = [
        # (label, username, password, expect_ok)
        ("pw len 0", base + "a", "", False),
        ("pw len 5", base + "b", "12345", False),
        ("pw len 6 (min)", base + "c", "123456", True),
        ("pw len 72 (max)", base + "d", "x" * 72, True),
        ("pw len 73 (max+1)", base + "e", "x" * 73, False),
        ("pw len 1000", base + "f", "x" * 1000, False),
        ("pw len 6 unicode", base + "g", u"中文密码六字", True),
        ("pw len 72 unicode (bytes over)", base + "h", u"密" * 40, None),  # judge candidate
        ("user len 32 (max)", "u" * 32, "123456", True),
        ("user len 33 (max+1)", "u" * 33, "123456", False),
        ("user empty", "", "123456", False),
        ("user unicode 8", base + u"用", "123456", None),
    ]
    for label, user, pw, expect_ok in cases:
        drop_user(user)
        s, b, raw = safe_request("POST", "users+create", {"userName": user, "password": pw})
        c = code_of(b)
        accepted = ok(b)
        print("%s -> code=%s raw=%s" % (label, c, raw[:200]))
        if expect_ok is False and accepted:
            defects.append("%s accepted (code 0), contract requires 1100 rejection" % label)
        if expect_ok is True and not accepted:
            print("  NOTE: legal value rejected (code=%s) - contract/judge candidate" % c)
        if (not accepted) and c != 1100 and c is not None:
            print("  NOTE: rejected with code=%s != 1100 (Type2 candidate)" % c)
        drop_user(user)

    if defects:
        for d in defects:
            print("DEFECT: %s" % d)
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - password/username range violation accepted")
    else:
        print("VERDICT: NO_DEFECT")

if __name__ == "__main__":
    main()
