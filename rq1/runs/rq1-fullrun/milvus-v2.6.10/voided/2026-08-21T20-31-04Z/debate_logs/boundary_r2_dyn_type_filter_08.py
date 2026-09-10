#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script (R2)
Target: milvus v2.6.10 (REST v2 /v2/vectordb)
Attack: type boundary - dynamic field established with int, then FILTERED as string and
reverse (mixed-type semantics at query time); also null/None JSON value for a dynamic
field (null_handling surface) (strategy 2/4)
Constraint: milvus_type_dynamic_field_consistency_001
Endpoints: entities+insert, entities+query, entities+delete
Blindspot: BS-01 Parameter Coercion Trust
R1 uncovered: query-side semantic behavior against dynamic field types + null values.
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
COLL = "bnd_r2_dtf_" + TS


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

st, b, raw = safe_request("POST", "entities+insert", {
    "collectionName": COLL,
    "data": [{"id": 1, "vec": [0.1] * DIM, "nf": 10},
             {"id": 2, "vec": [0.2] * DIM, "sf": "abc"}]})
print("insert dyn int+str -> ok=%s raw=%s" % (is_ok(b), raw[:150]))
if not is_ok(b):
    print("VERDICT: SCRIPT_ERROR - seed insert failed")
    sys.exit(2)
# v2.6 requires an index before load (code 700 index not found)
st, b, raw = safe_request("POST", "indexes+create", {
    "collectionName": COLL,
    "indexParams": [{"fieldName": "vec", "metricType": "L2",
                     "params": {"index_type": "FLAT"}}]})
print("index create -> ok=%s raw=%s" % (is_ok(b), raw[:150]))
st, b, raw = safe_request("POST", "collections+load", {"collectionName": COLL})
for _ in range(60):
    st2, b2, raw2 = safe_request("POST", "collections+get_load_state",
                                 {"collectionName": COLL})
    if '"LoadState":"Loaded"' in raw2 or '"LoadState":"LoadStateLoaded"' in raw2        or (isinstance(b2, dict) and str(b2.get("data", {}).get("loadState", "")).endswith("Loaded")):
        break
    time.sleep(1)

defects = []

# null value for dynamic field (null_handling)
st, b, raw = safe_request("POST", "entities+insert", {
    "collectionName": COLL,
    "data": [{"id": 3, "vec": [0.1] * DIM, "nullf": None}]})
ok = is_ok(b)
print("insert dyn field = None -> ok=%s raw=%s" % (ok, raw[:180]))
if ok:
    # if accepted, read back: was it stored / does it break later same-field typed insert?
    st2, b2, raw2 = safe_request("POST", "entities+insert", {
        "collectionName": COLL,
        "data": [{"id": 4, "vec": [0.1] * DIM, "nullf": 5}]})
    print("  then nullf=5 -> ok=%s raw=%s" % (is_ok(b2), raw2[:150]))

# filter mismatched type: nf is int, filter as string literal
st, b, raw = safe_request("POST", "entities+query", {
    "collectionName": COLL, "filter": 'nf == "10"', "outputFields": ["id"]})
ok = is_ok(b)
print("query filter nf=='10' (int field, str literal) -> ok=%s raw=%s" % (ok, raw[:200]))
if ok:
    results = b.get("data") if isinstance(b, dict) else None
    if results:  # matched rows via type-coerced comparison = semantic defect
        defects.append("filter type coercion: int dynamic field matched string literal "
                       "-> results=%s" % str(results)[:120])

# filter mismatched reverse: sf is string, filter as int
st, b, raw = safe_request("POST", "entities+query", {
    "collectionName": COLL, "filter": "sf == 0", "outputFields": ["id"]})
print("query filter sf==0 (str field, int literal) -> ok=%s raw=%s" % (is_ok(b), raw[:200]))

# delete with mismatched-type filter
st, b, raw = safe_request("POST", "entities+delete", {
    "collectionName": COLL, "filter": 'nf == "10"'})
print("delete filter nf=='10' -> ok=%s raw=%s" % (is_ok(b), raw[:180]))

if defects:
    for d in defects:
        print("DEFECT: %s" % d)
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess / semantic type coercion)")
    cleanup()
    sys.exit(1)
print("VERDICT: NO_DEFECT")
cleanup()
sys.exit(0)
