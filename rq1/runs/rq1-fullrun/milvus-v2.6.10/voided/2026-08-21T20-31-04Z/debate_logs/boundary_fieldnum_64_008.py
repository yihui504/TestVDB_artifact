#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.10 (REST v2 /v2/vectordb; contract '+' path translated to '/')
Attack: range boundary - maxFieldNum=64 / maxVectorFieldNum=4 (strategy 1)
Constraint: milvus_range_collections_create_003
Endpoint: collections+create
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


def build(n_scalar, n_vec):
    fields = [{"fieldName": "id", "dataType": "Int64", "isPrimary": True}]
    for i in range(n_scalar):
        fields.append({"fieldName": "f%d" % i, "dataType": "Int32"})
    for i in range(n_vec):
        fields.append({"fieldName": "v%d" % i, "dataType": "FloatVector", "elementTypeParams": {"dim": DIM}})
    return fields

results = []
for label, ns, nv in [("63 total (62 scalar+1 vec, ok-1)", 61, 1),
                      ("64 total", 62, 1),
                      ("65 total", 63, 1),
                      ("66 total", 64, 1),
                      ("5 vector fields", 0, 5),
                      ("5 vector + many scalar", 59, 5)]:
    coll = "bnd_fields_" + TS
    cleanup_drop(coll)
    st, b, raw = safe_request("POST", "collections+create",
                              {"collectionName": coll, "schema": {"fields": build(ns, nv)}})
    ok = is_ok(b)
    print("%s -> http=%s ok=%s raw=%s" % (label, st, ok, raw[:200]))
    if ok:
        cleanup_drop(coll)
    results.append((label, ns, nv, ok))

bad = [(l, nv) for l, ns, nv, ok in results if ok and (ns + nv + 1 > 64 or nv > 4)]
if bad:
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - field-count limits exceeded and accepted: %r" % bad)
else:
    print("VERDICT: NO_DEFECT")
