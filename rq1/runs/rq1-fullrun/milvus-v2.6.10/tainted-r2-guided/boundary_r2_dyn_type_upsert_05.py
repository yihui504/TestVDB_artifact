#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script (R2)
Target: milvus v2.6.10 (REST v2 /v2/vectordb)
Attack: type boundary - dynamic field TYPE consistency via entities/upsert; also
upsert-vs-insert channel switch (insert establishes, upsert violates, and reverse) (strategy 2)
Constraint: milvus_type_dynamic_field_consistency_001
Endpoint: entities+upsert, entities+insert
Blindspot: BS-01 Parameter Coercion Trust
R1 covered insert only; upsert channel + cross-channel switch uncovered.
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
COLL = "bnd_r2_dtu_" + TS


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

# scenario 1: upsert establishes string, upsert violates with int
st, b, raw = safe_request("POST", "entities+upsert",
                          {"collectionName": COLL,
                           "data": [{"id": 1, "vec": [0.1] * DIM, "uf": "str"}]})
print("upsert establish string -> ok=%s raw=%s" % (is_ok(b), raw[:150]))
st, b, raw = safe_request("POST", "entities+upsert",
                          {"collectionName": COLL,
                           "data": [{"id": 2, "vec": [0.1] * DIM, "uf": 42}]})
ok = is_ok(b)
print("upsert string->int -> ok=%s raw=%s" % (ok, raw[:180]))
if ok:
    defects.append("upsert channel: dynf string->int accepted")

# scenario 2: insert establishes int, upsert violates with string
st, b, raw = safe_request("POST", "entities+insert",
                          {"collectionName": COLL,
                           "data": [{"id": 3, "vec": [0.1] * DIM, "if_": 7}]})
print("insert establish int -> ok=%s" % is_ok(b))
st, b, raw = safe_request("POST", "entities+upsert",
                          {"collectionName": COLL,
                           "data": [{"id": 3, "vec": [0.1] * DIM, "if_": "str"}]})
ok = is_ok(b)
print("upsert int->string -> ok=%s raw=%s" % (ok, raw[:180]))
if ok:
    defects.append("cross-channel: insert int -> upsert string accepted")

# scenario 3: bool then int via upsert
st, b, raw = safe_request("POST", "entities+upsert",
                          {"collectionName": COLL,
                           "data": [{"id": 4, "vec": [0.1] * DIM, "bf": True}]})
print("upsert establish bool -> ok=%s" % is_ok(b))
st, b, raw = safe_request("POST", "entities+upsert",
                          {"collectionName": COLL,
                           "data": [{"id": 5, "vec": [0.1] * DIM, "bf": 9}]})
ok = is_ok(b)
print("upsert bool->int -> ok=%s raw=%s" % (ok, raw[:180]))
if ok:
    defects.append("upsert channel: dynf bool->int accepted")

if defects:
    for d in defects:
        print("DEFECT: %s" % d)
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)")
    cleanup()
    sys.exit(1)
print("VERDICT: NO_DEFECT")
cleanup()
sys.exit(0)
