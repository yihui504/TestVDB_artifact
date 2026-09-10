#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script (R2b)
Target: milvus v2.6.10 (REST v2 /v2/vectordb)
Attack: upsert row-face: type-confused values for typed schema fields (strategy 2)
Constraint: milvus_type_entities_insert_001 (rows must match schema types)
Endpoints: entities+upsert, entities+query
R1 uncovered: upsert (not insert) with wrong scalar types (Int64 field given
string / VarChar given int), extra unknown keys in strict-ish schema, and
vector given as string.
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
COLL = "bnd_r2b_ups_" + TS


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
        "enableDynamicField": False,
        "fields": [
            {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
            {"fieldName": "vc", "dataType": "VarChar",
             "elementTypeParams": {"max_length": 64}},
            {"fieldName": "num", "dataType": "Int64"},
            {"fieldName": "vec", "dataType": "FloatVector",
             "elementTypeParams": {"dim": DIM}}]}})
if not is_ok(b):
    print("VERDICT: SCRIPT_ERROR - setup create failed: %s" % raw[:200])
    sys.exit(2)

defects = []
cases = [
    ("Int64 pk as string", {"id": "1", "vc": "a", "num": 1, "vec": [0.1] * DIM}),
    ("Int64 field as string", {"id": 2, "vc": "a", "num": "5", "vec": [0.1] * DIM}),
    ("VarChar field as int", {"id": 3, "vc": 123, "num": 1, "vec": [0.1] * DIM}),
    ("vector as string", {"id": 4, "vc": "a", "num": 1, "vec": "not-a-vector"}),
    ("unknown extra key", {"id": 5, "vc": "a", "num": 1, "vec": [0.1] * DIM,
                            "ghost_key": "x"}),
    ("null pk", {"id": None, "vc": "a", "num": 1, "vec": [0.1] * DIM}),
]
for name, row in cases:
    st, b, raw = safe_request("POST", "entities+upsert", {
        "collectionName": COLL, "data": [row]})
    ok = is_ok(b)
    print("upsert %s -> http=%s ok=%s raw=%s" % (name, st, ok, raw[:200]))
    if ok:
        defects.append("upsert accepted %s silently (code=0)" % name)

# readback check for any accepted string-pk / string-int rows
st, b, raw = safe_request("POST", "entities+query", {
    "collectionName": COLL, "filter": "id >= 0", "outputFields": ["id", "vc", "num"]})
print("readback -> ok=%s raw=%s" % (is_ok(b), raw[:300]))

if defects:
    for d in defects:
        print("DEFECT: %s" % d)
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess / upsert type confusion)")
    cleanup()
    sys.exit(1)
print("VERDICT: NO_DEFECT")
cleanup()
sys.exit(0)
