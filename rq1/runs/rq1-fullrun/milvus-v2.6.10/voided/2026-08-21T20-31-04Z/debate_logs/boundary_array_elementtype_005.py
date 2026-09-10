#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.10 (REST v2 /v2/vectordb; contract '+' path translated to '/')
Attack: type boundary - Array without elementDataType (strategy 2)
Constraint: milvus_type_collections_create_006
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


COLL = "bnd_array_elt_" + TS
cases = {
    "no elementDataType": {"fieldName": "arr", "dataType": "Array"},
    "elementDataType null": {"fieldName": "arr", "dataType": "Array", "elementDataType": None},
    "elementDataType Int64": {"fieldName": "arr", "dataType": "Array", "elementDataType": "Int64"},
    "elementDataType bogus": {"fieldName": "arr", "dataType": "Array", "elementDataType": "FooBar"},
    "elementDataType on VarChar field": {"fieldName": "arr", "dataType": "VarChar", "elementDataType": "Int64", "maxLength": 32},
}
for label, field in cases.items():
    cleanup_drop(COLL)
    fields = [{"fieldName": "id", "dataType": "Int64", "isPrimary": True}, field,
              {"fieldName": "vec", "dataType": "FloatVector", "elementTypeParams": {"dim": DIM}}]
    st, b, raw = safe_request("POST", "collections+create",
                              {"collectionName": COLL, "schema": {"fields": fields}})
    ok = is_ok(b)
    print("%s -> http=%s ok=%s raw=%s" % (label, st, ok, raw[:220]))
    if ok:
        st2, b2, raw2 = safe_request("POST", "collections+describe", {"collectionName": COLL})
        print("  describe: %s" % raw2[:400])
        if label == "no elementDataType":
            print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - Array without elementDataType accepted")
            sys.exit(1)
    elif label == "elementDataType bogus" and isinstance(b, dict) and b.get("code") != 1100:
        print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) - bogus elementDataType code=%s" % b.get("code"))
        sys.exit(1)
cleanup_drop(COLL)
print("VERDICT: NO_DEFECT")
