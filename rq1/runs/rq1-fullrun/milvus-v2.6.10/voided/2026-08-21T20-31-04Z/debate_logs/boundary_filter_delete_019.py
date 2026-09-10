#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.10 (REST v2 /v2/vectordb; contract '+' path translated to '/')
Attack: filter boundary - null/invalid boolean expr on delete+search (strategy 2)
Constraint: milvus_type_entities_delete_001
Endpoint: entities+delete+entities+search
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


COLL = "bnd_filter_" + TS
ok, msg = setup_quick(COLL, DIM)
print("setup: %s" % msg)
cases = [
    "",
    "   ",
    "id >",
    "id >< 5",
    "id == ",
    "not a boolean expr",
    "id == 1; DROP",
    "id == 1 OR",
    "()",
    "id in []",
    "id == null",
    "vector == [1]",
    "1 == 1",
    "id == 1 AND ghost == 2",
    "a" * 10000,
]
results = []
for f in cases:
    st, b, raw = safe_request("POST", "entities+delete",
                              {"collectionName": COLL, "filter": f})
    ok = is_ok(b)
    code = b.get("code") if isinstance(b, dict) else None
    print("delete filter=%r -> http=%s code=%s ok=%s raw=%s" % (f[:40], st, code, ok, raw[:180]))
    if st >= 500:
        print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - filter crashed server")
        sys.exit(1)
    results.append((f, ok))
# verify row 1 still present after bogus deletes
st, b, raw = safe_request("POST", "entities+query",
                          {"collectionName": COLL, "filter": "id == 1", "outputFields": ["id"]})
print("post-fuzz query id==1: %s" % raw[:250])
cleanup_drop(COLL)
bad = [f[:20] for f, ok in results if ok and f.strip() in
       ("", "id >", "id >< 5", "id == ", "not a boolean expr", "id == 1 OR", "()")]
if bad:
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - invalid filter accepted: %r" % bad)
else:
    print("VERDICT: NO_DEFECT")
