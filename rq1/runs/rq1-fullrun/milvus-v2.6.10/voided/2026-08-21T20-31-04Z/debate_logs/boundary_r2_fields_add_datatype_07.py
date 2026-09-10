#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script (R2)
Target: milvus v2.6.10 (REST v2 /v2/vectordb)
Attack: type boundary - dataType enum/null/missing/type-confusion via collections/fields/add (strategy 2)
Constraint: milvus_type_collections_create_001 (dataType enum), _002 (required)
Endpoint: collections+fields+add (R1-uncovered endpoint)
Blindspot: BS-01 Parameter Coercion Trust
"""

import requests
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
    print("[FALLBACK_JUSTIFIED: raw_knowledge.md Document Sources live instance http://localhost:19530]")
AUTH = os.environ.get("TESTVDB_AUTH_HEADER", "Bearer root:Milvus")
API = BASE_URL.rstrip("/") + "/v2/vectordb"
DIM = 8
TS = str(int(time.time()))
COLL = "bnd_r2_fdt_" + TS


def safe_request(method, endpoint, payload=None, timeout=90):
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
    return isinstance(body, dict) and body.get("code") in (0, 200)


def cleanup():
    try:
        safe_request("POST", "collections+drop", {"collectionName": COLL})
    except Exception:
        pass


st, b, raw = safe_request("POST", "collections+create", {
    "collectionName": COLL,
    "schema": {"fields": [
        {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
        {"fieldName": "vec", "dataType": "FloatVector",
         "elementTypeParams": {"dim": DIM}}]}})
if not is_ok(b):
    print("VERDICT: SCRIPT_ERROR - setup create failed: %s" % raw[:200])
    sys.exit(2)

CASES = [
    ("dataType invalid enum", {"fieldName": "f_a", "dataType": "Int128"}),
    ("dataType bogus string", {"fieldName": "f_b", "dataType": "notAType"}),
    ("dataType null", {"fieldName": "f_c", "dataType": None}),
    ("dataType missing", {"fieldName": "f_d"}),
    ("dataType type confusion int", {"fieldName": "f_e", "dataType": 5}),
    ("dataType lowercase variant", {"fieldName": "f_f", "dataType": "int64"}),
    ("Vector field without dim via add",
     {"fieldName": "f_g", "dataType": "FloatVector"}),
    ("Array field without elementDataType",
     {"fieldName": "f_h", "dataType": "Array"}),
]
accepted = []
for label, extra in CASES:
    field = dict(extra)
    field.setdefault("nullable", True)
    payload = {"collectionName": COLL, "schema": field}
    st, b, raw = safe_request("POST", "collections+fields+add", payload)
    ok = is_ok(b)
    print("%s -> http=%s ok=%s raw=%s" % (label, st, ok, raw[:200]))
    if ok:
        accepted.append(label)

# control
st, b, raw = safe_request("POST", "collections+fields+add",
                          {"collectionName": COLL,
                           "schema": {"fieldName": "ok_field", "dataType": "Int64",
                                      "nullable": True}})
print("control valid -> ok=%s" % is_ok(b))

if accepted:
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - fields+add accepted: %r" % accepted)
    cleanup()
    sys.exit(1)
print("VERDICT: NO_DEFECT")
cleanup()
sys.exit(0)
