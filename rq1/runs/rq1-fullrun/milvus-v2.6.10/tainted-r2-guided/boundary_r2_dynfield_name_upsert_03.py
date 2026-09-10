#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script (R2)
Target: milvus v2.6.10 (REST v2 /v2/vectordb)
Attack: type boundary - dynamic field NAME rules via entities/upsert + schema-mode fieldName at create (strategy 2)
Constraint: milvus_type_field_name_rules_001
Endpoint: entities+upsert, collections+create (schema fieldName)
Blindspot: BS-01 Parameter Coercion Trust
R1 covered insert channel only; this covers upsert channel + create-schema channel.
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
COLL = "bnd_r2_dfn_ups_" + TS


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


# channel A: schema fieldName at create
bad_schema = []
for fn in ["123field", "@field", "my-field"]:
    cleanup()
    st, b, raw = safe_request("POST", "collections+create", {
        "collectionName": COLL,
        "schema": {"fields": [
            {"fieldName": fn, "dataType": "Int64", "isPrimary": True},
            {"fieldName": "vec", "dataType": "FloatVector",
             "elementTypeParams": {"dim": DIM}}]}})
    ok = is_ok(b)
    print("create schema fieldName=%r -> ok=%s raw=%s" % (fn, ok, raw[:180]))
    if ok:
        bad_schema.append(fn)
cleanup()

# channel B: upsert with illegal dynamic field names
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

bad_upsert = []
for i, fn in enumerate(["123field", "@field", "my-field"]):
    st, b, raw = safe_request("POST", "entities+upsert", {
        "collectionName": COLL,
        "data": [{"id": 300 + i, "vec": [0.1] * DIM, fn: "v"}]})
    ok = is_ok(b)
    print("upsert dyn field %r -> ok=%s raw=%s" % (fn, ok, raw[:180]))
    if ok:
        bad_upsert.append(fn)

if bad_schema or bad_upsert:
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - illegal fieldName accepted: "
          "create=%r upsert=%r" % (bad_schema, bad_upsert))
    cleanup()
    sys.exit(1)
print("VERDICT: NO_DEFECT")
cleanup()
sys.exit(0)
