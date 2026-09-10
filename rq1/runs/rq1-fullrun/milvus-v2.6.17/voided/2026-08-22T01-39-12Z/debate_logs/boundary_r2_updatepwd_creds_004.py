#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script R2
Target: milvus v2.6.17
Attack: users/update_password credential-shape boundary: wrong oldPassword vs missing,
empty strings, changing root's password guard, new password bounds
Endpoint: users/update_password (untested surface in R1)
Contract: users+create family password rule 6<=len<=72 (same validator expected here)
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import safe_request, code_of

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TAG = "r2upw%d" % (int(time.time()) % 100000)
USER = TAG + "_u"
PWD = "abcdef"


def upd(user, old, new, note):
    p = {"userName": user}
    if old is not None:
        p["password"] = old
    if new is not None:
        p["newPassword"] = new
    s, b, raw = safe_request("POST", "users/update_password", p)
    cd = code_of(b)
    print("%-52s -> code=%-5s %s" % (note, cd, raw[:150]))
    return cd, raw


def main():
    s, b, raw = safe_request("POST", "users+create",
                             {"userName": USER, "password": PWD})
    print("setup user: code=%s" % code_of(b))
    findings = []

    # wrong old password: should be rejected
    cd, _ = upd(USER, "wrong!", "newpass1", "wrong password(old)")
    if cd == 0:
        findings.append("update_password with WRONG oldPassword succeeded - credential check bypass")

    # missing oldPassword key entirely
    cd, _ = upd(USER, None, "newpass2", "missing password(old) key")
    if cd == 0:
        findings.append("update_password without oldPassword succeeded - auth bypass shape")

    # empty oldPassword ""
    cd, _ = upd(USER, "", "newpass3", "empty password(old)")
    if cd == 0:
        findings.append("update_password with empty oldPassword succeeded")

    # new password out of range (len 3) - same validator expected
    cd, raw = upd(USER, PWD, "abc", "newPassword len 3 (min 6)")
    if cd == 0:
        findings.append("newPassword len 3 accepted on update path (min 6 not enforced)")

    # new password len 73
    cd, raw = upd(USER, PWD, "a" * 73, "newPassword len 73 (max 72)")
    if cd == 0:
        findings.append("newPassword len 73 accepted on update path")

    # legitimate change then verify old cred fails / new works
    cd, raw = upd(USER, PWD, "newpass9", "legit change")
    if cd == 0:
        import requests
        url = os.environ.get("TESTVDB_DB_URL", "http://localhost:19530").rstrip("/") + "/v2/vectordb/users/list"
        r1 = requests.post(url, headers={"Authorization": "Bearer %s:%s" % (USER, PWD)}, data="{}")
        r2 = requests.post(url, headers={"Authorization": "Bearer %s:newpass9" % USER}, data="{}")
        print("old cred -> HTTP %s | new cred -> HTTP %s" % (r1.status_code, r2.status_code))
        import time as _t
        still = False
        for _ in range(3):
            _t.sleep(1)
            rr = requests.post(url, headers={"Authorization": "Bearer %s:%s" % (USER, PWD)}, data="{}")
            if rr.status_code == 200:
                still = True
        if still:
            findings.append("OLD password STILL valid >=3s after successful change (credential cache not invalidated)")

    # root guard: attempt root password change with wrong old
    cd, raw = upd("root", "definitely-wrong", "hacked12", "root with wrong oldPassword")
    if cd == 0:
        findings.append("CRITICAL: root password changed with wrong oldPassword")
        # restore
        safe_request("POST", "users/update_password",
                     {"userName": "root", "password": "hacked12", "newPassword": "Milvus"})

    try:
        safe_request("POST", "users+drop", {"userName": USER})
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
