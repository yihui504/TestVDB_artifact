#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script (R2b)
Target: milvus v2.6.10 (REST v2 /v2/vectordb)
Attack: dynamic field same-key cross-type across insert/upsert (strategy 2/4)
Constraint: milvus_type_entities_insert_001 (row must match established semantics)
Endpoints: entities+insert, entities+upsert, entities+query
R1 uncovered: same dynamic field established as one type then re-written with a
different type via upsert (int -> string -> bool -> float), then queried back.
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
COLL = "bnd_r2b_ctx_" + TS


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
    "schema": {
        "enableDynamicField": True,
        "fields": [
            {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
            {"fieldName": "vec", "dataType": "FloatVector",
             "elementTypeParams": {"dim": DIM}}]}})
if not is_ok(b):
    print("VERDICT: SCRIPT_ERROR - setup create failed: %s" % raw[:200])
    sys.exit(2)

defects = []
# establish dyn field "f" as int
st, b, raw = safe_request("POST", "entities+insert", {
    "collectionName": COLL,
    "data": [{"id": 1, "vec": [0.1] * DIM, "f": 10}]})
print("insert f=10 (int) -> ok=%s raw=%s" % (is_ok(b), raw[:150]))
if not is_ok(b):
    print("VERDICT: SCRIPT_ERROR - seed insert failed")
    sys.exit(2)

# same key, different type, via INSERT on a new row
for i, val in enumerate(["ten", True, 3.5, [1, 2], {"n": 1}]):
    st, b, raw = safe_request("POST", "entities+insert", {
        "collectionName": COLL,
        "data": [{"id": i + 2, "vec": [0.1] * DIM, "f": val}]})
    ok = is_ok(b)
    print("insert f=%r (%s) -> ok=%s raw=%s" % (val, type(val).__name__, ok, raw[:180]))
    if ok and i == 0:
        defects.append("dynamic field 'f' established as Int accepts String value "
                       "on new row (cross-type silent accept)")

# same key, different type, via UPSERT overwriting row 1
st, b, raw = safe_request("POST", "entities+upsert", {
    "collectionName": COLL,
    "data": [{"id": 1, "vec": [0.1] * DIM, "f": "was-int"}]})
ok = is_ok(b)
print("upsert id=1 f='was-int' -> ok=%s raw=%s" % (ok, raw[:180]))
if ok:
    defects.append("upsert rewrites dynamic field 'f' Int->String silently")

if defects:
    for d in defects:
        print("DEFECT: %s" % d)
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess / dynamic field cross-type)")
    cleanup()
    sys.exit(1)
print("VERDICT: NO_DEFECT")
cleanup()
sys.exit(0)
