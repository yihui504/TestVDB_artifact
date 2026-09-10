#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.10 (REST v2 /v2/vectordb; contract '+' path translated to '/')
Attack: range boundary - user password 6..72 / username <= 32 (strategy 1)
Constraint: milvus_range_users_create_001
Endpoint: users+create
Blindspot: BS-01 Parameter Coercion Trust / BS-04 Boundary Default Optimism
Note: Milvus v2 success envelope = HTTP 200 + JSON code==0 (v1 legacy code==200).
      Error = HTTP 200 + nonzero JSON code (e.g. 1100 invalid param). Verdict uses JSON code.
"""

import requests
import json
import sys
import os
import time

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    BASE_URL = "http://localhost:19530"
    print("FALLBACK_TRIGGERED: TESTVDB_DB_URL not set, defaulting to contract live instance")
    print("[FALLBACK_JUSTIFIED: raw_knowledge.md Document Sources #13 'live instance http://localhost:19530']")
AUTH = os.environ.get("TESTVDB_AUTH_HEADER", "Bearer root:Milvus")
API = BASE_URL.rstrip("/") + "/v2/vectordb"
DIM = 8
TS = str(int(time.time()))


def safe_request(method, endpoint, payload=None, timeout=90):
    """endpoint uses contract '+' form, translated to '/'. Returns (http_status, body, raw_text)."""
    url = "%s/%s" % (API, endpoint.replace("+", "/"))
    try:
        r = requests.request(method, url, json=payload,
                             headers={"Content-Type": "application/json",
                                      "Authorization": AUTH},
                             timeout=timeout)
        try:
            body = r.json()
        except Exception:
            body = r.text
        return r.status_code, body, r.text
    except Exception as e:
        return -1, str(e), str(e)


def is_ok(body):
    """Milvus v2 success envelope: code==0 (or v1 legacy 200)."""
    return isinstance(body, dict) and body.get("code") in (0, 200)


def is_err_code(body, *codes):
    return isinstance(body, dict) and body.get("code") in codes


def cleanup_drop(coll):
    try:
        safe_request("POST", "collections+drop", {"collectionName": coll})
    except Exception:
        pass


def setup_quick(coll, dim=DIM):
    """Quick-mode create + insert + load + flush-ish wait. Returns (ok, msg)."""
    st, b, raw = safe_request("POST", "collections+create",
                              {"collectionName": coll, "dimension": dim})
    if not is_ok(b):
        return False, "create failed: " + raw[:300]
    st, b, raw = safe_request("POST", "entities+insert",
                              {"collectionName": coll,
                               "data": [{"id": 1, "vector": [0.1] * dim}]})
    if not is_ok(b):
        return False, "insert failed: " + raw[:300]
    for _ in range(30):
        st, b, raw = safe_request("POST", "collections+load", {"collectionName": coll})
        if is_ok(b):
            return True, "ready"
        time.sleep(1)
    return False, "load timeout"


user = "bndu_" + TS[-6:]
st, b, raw = safe_request("POST", "users+create", {"userName": user, "password": "Passw0rd!"})
print("create user -> http=%s ok=%s raw=%s" % (st, is_ok(b), raw[:200]))

cases = [
    ("len 5", "a" * 5), ("len 6", "a" * 6), ("len 7", "a" * 7),
    ("len 71", "a" * 71), ("len 72", "a" * 72), ("len 73", "a" * 73),
    ("len 1000", "a" * 1000),
    ("empty", ""), ("null", None), ("int", 12345),
    ("unicode", "中文密码" * 10),
]
results = []
for label, pw in cases:
    st, b, raw = safe_request("POST", "users+update_password",
                              {"userName": user, "oldPassword": "Passw0rd!", "newPassword": pw})
    ok = is_ok(b)
    print("password %s -> http=%s ok=%s raw=%s" % (label, st, ok, raw[:180]))
    if ok:
        # restore
        safe_request("POST", "users+update_password",
                     {"userName": user, "oldPassword": pw if isinstance(pw, str) and pw else "Passw0rd!",
                      "newPassword": "Passw0rd!"})
    results.append((label, pw, ok))
# username length
for label, un in [("uname 32", "u" * 32), ("uname 33", "u" * 33), ("uname 100", "u" * 100)]:
    st, b, raw = safe_request("POST", "users+create", {"userName": un, "password": "Passw0rd!"})
    ok = is_ok(b)
    print("username %s -> http=%s ok=%s raw=%s" % (label, st, ok, raw[:180]))
    if ok:
        try:
            safe_request("POST", "users+drop", {"userName": un})
        except Exception:
            pass
    results.append((label, un, ok))

bad = []
for label, v, ok in results:
    if not ok:
        continue
    if label.startswith("len") and isinstance(v, str):
        n = len(v)
        if n < 6 or n > 72:
            bad.append(label)
    if label.startswith("uname") and isinstance(v, str) and len(v) > 32:
        bad.append(label)
    if label in ("empty", "null", "int"):
        bad.append(label)
try:
    safe_request("POST", "users+drop", {"userName": user})
except Exception:
    pass
if bad:
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - out-of-range credential accepted: %r" % bad)
else:
    print("VERDICT: NO_DEFECT")
