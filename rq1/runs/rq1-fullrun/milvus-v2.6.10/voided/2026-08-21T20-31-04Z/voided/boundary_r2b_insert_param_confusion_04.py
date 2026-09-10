#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script (R2b)
Target: milvus v2.6.10 (REST v2 /v2/vectordb)
Attack: request-level type confusion on data-path params (strategy 2)
Constraint: milvus_type_entities_insert_001 (structure of insert request)
Endpoints: entities+insert, entities+upsert
R1 uncovered: request param types (data as object instead of array, rows as
arrays instead of objects, partitionNames as string, timeout as string).
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
COLL = "bnd_r2b_pcf_" + TS


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

defects = []
cases = [
    ("data as object", {"collectionName": COLL,
                        "data": {"id": 1, "vec": [0.1] * DIM}}),
    ("rows as arrays", {"collectionName": COLL,
                        "data": [[2, [0.1] * DIM]]}),
    ("data as string", {"collectionName": COLL, "data": "rows"}),
    ("partitionNames as string", {"collectionName": COLL,
                                   "partitionNames": "_default",
                                   "data": [{"id": 3, "vec": [0.1] * DIM}]}),
    ("timeout as string", {"collectionName": COLL, "timeout": "10",
                           "data": [{"id": 4, "vec": [0.1] * DIM}]}),
    ("data null", {"collectionName": COLL, "data": None}),
]
for name, payload in cases:
    st, b, raw = safe_request("POST", "entities+insert", payload)
    ok = is_ok(b)
    print("insert %s -> http=%s ok=%s raw=%s" % (name, st, ok, raw[:200]))
    if ok:
        # verify nothing corrupt was persisted
        st2, b2, raw2 = safe_request("POST", "entities+query", {
            "collectionName": COLL, "filter": "id >= 0", "outputFields": ["id"]})
        print("  readback ok=%s raw=%s" % (is_ok(b2), raw2[:150]))
        defects.append("insert accepted %s (code=0)" % name)

# same faces on upsert
st, b, raw = safe_request("POST", "entities+upsert", {
    "collectionName": COLL, "data": {"id": 9, "vec": [0.1] * DIM}})
ok = is_ok(b)
print("upsert data-as-object -> ok=%s raw=%s" % (ok, raw[:200]))
if ok:
    defects.append("upsert accepted data as object")

if defects:
    for d in defects:
        print("DEFECT: %s" % d)
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess / request param type confusion)")
    cleanup()
    sys.exit(1)
print("VERDICT: NO_DEFECT")
cleanup()
sys.exit(0)
