#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script R2
Target: milvus v2.6.17
Attack: password boundary SHAPES beyond plain ASCII length (bytes vs chars, unicode, NUL, empty)
Constraint: milvus_range_users_create_password_002, milvus_range_users_create_001
R1 tested len 5 only. R2 probes:
  - len 6 all-unicode multibyte (6 chars, 18 bytes) -> in-range by chars but > bytes?
  - exactly 72 chars, 73 chars (upper boundary untested live)
  - empty string "" and missing password key
  - NUL byte inside password (bcrypt truncates at NUL historically)
  - control chars / long whitespace
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import safe_request, code_of

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import time
TAG = "r2pw%d" % (int(time.time()) % 100000)


def try_user(name, pwd, note):
    payload = {"userName": name}
    if pwd is not None:
        payload["password"] = pwd
    s, b, raw = safe_request("POST", "users+create", payload)
    cd = code_of(b)
    print("%-38s -> code=%-5s %s" % (note, cd, raw[:140]))
    return cd, raw


def main():
    findings = []
    # 6 unicode chars = 18 UTF-8 bytes: is bound by chars or bytes?
    cd, raw = try_user(TAG + "u6", "密密密密密密", "6 unicode chars (18 bytes)")
    if cd == 0:
        print("  -> accepted: bound is per-char (len() in Go counts bytes usually -> 18 > 6? but accepted)")
    elif cd == 1100:
        print("  -> rejected by byte count")

    # upper boundary 72 / 73
    cd72, _ = try_user(TAG + "p72", "a" * 72, "72 chars (at max)")
    cd73, _ = try_user(TAG + "p73", "a" * 73, "73 chars (max+1)")
    if cd73 == 0:
        findings.append("password len 73 accepted (max documented 72) - upper bound not enforced")
    if cd72 != 0:
        findings.append("password len 72 rejected although max is 72")

    # empty / missing
    cdE, _ = try_user(TAG + "e0", "", "empty string password")
    if cdE == 0:
        findings.append("empty password accepted (min 6)")
    cdM, _ = try_user(TAG + "m0", None, "missing password key")
    if cdM == 0:
        findings.append("missing password key accepted")

    # NUL byte: bcrypt truncation risk
    cdN, rawN = try_user(TAG + "n0", "ab\u0000cd" + "x" * 10, "NUL inside password (len 15)")
    if cdN == 0:
        import requests
        url = os.environ.get("TESTVDB_DB_URL", "http://localhost:19530").rstrip("/") + "/v2/vectordb/collections/list"
        r = requests.post(url, headers={"Authorization": "Bearer %s:ab" % (TAG + "n0"),
                                        "Content-Type": "application/json"}, data="{}")
        print("  auth with NUL-truncated pwd 'ab' -> HTTP %s %s" % (r.status_code, r.text[:100]))
        if r.status_code == 200:
            findings.append("NUL-truncated password 'ab' authenticates (bcrypt truncation at NUL): auth bypass shape")
        full_pwd = "ab\u0000cd" + "x" * 10
        r2 = requests.post(url, headers={"Authorization": "Bearer %s:%s" % (TAG + "n0", full_pwd),
                                         "Content-Type": "application/json"}, data="{}")
        print("  auth with full pwd -> HTTP %s %s" % (r2.status_code, r2.text[:100]))

    # username boundary: 32 ok / 33
    cdU33, _ = try_user("u" * 33 + TAG, "abcdef", "username 33+ chars (max 32)")
    if cdU33 == 0:
        findings.append("username >32 chars accepted (max 32)")

    # cleanup
    for n in (TAG + "u6", TAG + "p72", TAG + "p73", TAG + "e0", TAG + "m0", TAG + "n0"):
        try:
            safe_request("POST", "users+drop", {"userName": n})
        except Exception:
            pass
    try:
        safe_request("POST", "users+drop", {"userName": "u" * 33 + TAG})
    except Exception:
        pass

    if findings:
        for f in findings:
            print("FINDING: " + f)
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)")
    else:
        print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
