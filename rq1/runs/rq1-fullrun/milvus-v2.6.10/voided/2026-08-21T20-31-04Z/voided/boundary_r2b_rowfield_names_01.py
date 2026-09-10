#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script (R2b)
Target: milvus v2.6.10 (REST v2 /v2/vectordb)
Attack: data-row field-name legality + readback (strategy 1/2)
Constraint: milvus_range_collections_create_002 (name rules, applied to data keys)
Endpoint: entities+insert, entities+query
R1 uncovered: data-row keys (dynamic fields) with names illegal as identifiers
(digit-leading, hyphen, space, $, unicode) and whether accepted keys are
readable back via output_fields.
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
COLL = "bnd_r2b_rfn_" + TS


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

WEIRD = ["1abc", "my-key", "a b", "f$eld", "中文字段"]
accepted = {}
for i, k in enumerate(WEIRD):
    st, b, raw = safe_request("POST", "entities+insert", {
        "collectionName": COLL,
        "data": [{"id": i + 1, "vec": [0.1] * DIM, k: "v%d" % i}]})
    ok = is_ok(b)
    print("insert row key %r -> http=%s ok=%s raw=%s" % (k, st, ok, raw[:180]))
    if ok:
        accepted[k] = i + 1

defects = []
if accepted:
    # per-key readback: isolate which keys are readable vs not
    for k, rid in accepted.items():
        st, b, raw = safe_request("POST", "entities+query", {
            "collectionName": COLL, "filter": "id == %d" % rid,
            "outputFields": [k]})
        ok = is_ok(b)
        val = None
        if ok and isinstance(b, dict):
            data = b.get("data")
            if isinstance(data, list) and data and isinstance(data[0], dict):
                val = data[0].get(k, "<<ABSENT>>")
        print("readback %r -> ok=%s value=%r raw=%s" % (k, ok, val, raw[:200]))
        if not ok:
            defects.append("insert accepted key %r but output_fields readback "
                           "rejects it: %s" % (k, raw[:120]))
        elif val == "<<ABSENT>>":
            defects.append("insert accepted key %r but readback row lacks it "
                           "(silent data loss)" % k)

if defects:
    for d in defects:
        print("DEFECT: %s" % d)
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess / asymmetric row-key handling)")
    cleanup()
    sys.exit(1)
print("VERDICT: NO_DEFECT")
cleanup()
sys.exit(0)
