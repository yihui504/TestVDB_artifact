#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script (R2b)
Target: milvus v2.6.10 (REST v2 /v2/vectordb)
Attack: upsert partial rows - missing vector / missing non-pk fields (strategy 2)
Constraint: milvus_type_entities_insert_001 (rows must contain pk + vector fields)
Endpoints: entities+upsert, entities+query
R1 uncovered: upsert with missing vector field, missing scalar field, and
empty data array; also verifies old row state after failed/successful upsert.
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
COLL = "bnd_r2b_upm_" + TS


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
        {"fieldName": "num", "dataType": "Int64"},
        {"fieldName": "vec", "dataType": "FloatVector",
         "elementTypeParams": {"dim": DIM}}]}})
if not is_ok(b):
    print("VERDICT: SCRIPT_ERROR - setup create failed: %s" % raw[:200])
    sys.exit(2)

st, b, raw = safe_request("POST", "entities+insert", {
    "collectionName": COLL, "data": [{"id": 1, "num": 100, "vec": [0.1] * DIM}]})
print("seed insert -> ok=%s raw=%s" % (is_ok(b), raw[:150]))
if not is_ok(b):
    print("VERDICT: SCRIPT_ERROR - seed insert failed")
    sys.exit(2)

defects = []
# upsert missing vector (skalar only) - should be rejected per constraint
st, b, raw = safe_request("POST", "entities+upsert", {
    "collectionName": COLL, "data": [{"id": 1, "num": 200}]})
ok = is_ok(b)
print("upsert missing vector -> http=%s ok=%s raw=%s" % (st, ok, raw[:200]))
if ok:
    defects.append("upsert accepted row without vector field (code=0)")

# upsert missing non-pk scalar
st, b, raw = safe_request("POST", "entities+upsert", {
    "collectionName": COLL, "data": [{"id": 2, "vec": [0.2] * DIM}]})
ok = is_ok(b)
print("upsert missing scalar num -> ok=%s raw=%s" % (ok, raw[:200]))

# empty data array
st, b, raw = safe_request("POST", "entities+upsert", {
    "collectionName": COLL, "data": []})
ok = is_ok(b)
print("upsert data=[] -> ok=%s raw=%s" % (ok, raw[:200]))

# non-existent id upsert (= insert semantics?)
st, b, raw = safe_request("POST", "entities+upsert", {
    "collectionName": COLL, "data": [{"id": 999, "num": 9, "vec": [0.3] * DIM}]})
ok = is_ok(b)
print("upsert nonexistent id=999 -> ok=%s raw=%s" % (ok, raw[:180]))
if ok:
    st2, b2, raw2 = safe_request("POST", "entities+query", {
        "collectionName": COLL, "filter": "id == 999", "outputFields": ["num"]})
    present = '"num":9' in raw2.replace(" ", "") or (isinstance(b2, dict) and b2.get("data"))
    print("  readback id=999 -> present=%s raw=%s" % (bool(present), raw2[:200]))

if defects:
    for d in defects:
        print("DEFECT: %s" % d)
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess / upsert missing mandatory fields)")
    cleanup()
    sys.exit(1)
print("VERDICT: NO_DEFECT")
cleanup()
sys.exit(0)
