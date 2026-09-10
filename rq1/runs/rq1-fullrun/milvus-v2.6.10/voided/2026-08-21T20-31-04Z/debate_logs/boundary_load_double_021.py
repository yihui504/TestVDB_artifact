#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.10 (REST v2 /v2/vectordb; contract '+' path translated to '/')
Attack: state boundary - double load code 104 + search-not-loaded code 101 (control)
Constraint: milvus_state_collections_load_001 + milvus_state_collections_load_002
Endpoint: collections+load+entities+search
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


COLL = "bnd_load_" + TS
cleanup_drop(COLL)
st, b, raw = safe_request("POST", "collections+create",
                          {"collectionName": COLL, "dimension": DIM})
print("create: %s" % raw[:150])

# search on NOT_LOADED collection -> expect envelope code 101
st, b, raw = safe_request("POST", "entities+search",
                          {"collectionName": COLL, "data": [[0.1] * DIM], "limit": 1})
code = b.get("code") if isinstance(b, dict) else None
print("search before load -> http=%s code=%s raw=%s" % (st, code, raw[:250]))

ok, msg = setup_load = (None, None)
for _ in range(30):
    st, b, raw = safe_request("POST", "collections+load", {"collectionName": COLL})
    if is_ok(b):
        break
    time.sleep(1)

# second load -> expect code 104 (already loaded)
st, b, raw = safe_request("POST", "collections+load", {"collectionName": COLL})
code2 = b.get("code") if isinstance(b, dict) else None
print("double load -> http=%s code=%s raw=%s" % (st, code2, raw[:250]))
cleanup_drop(COLL)

issues = []
if code != 101:
    issues.append("search-not-loaded code=%r (expected 101)" % code)
if code2 != 104:
    issues.append("double-load code=%r (expected 104)" % code2)
if issues:
    print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) - %s" % "; ".join(issues))
else:
    print("VERDICT: NO_DEFECT")
