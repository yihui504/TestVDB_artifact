#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script (R2)
Target: milvus v2.6.10 (REST v2 /v2/vectordb)
Attack: type boundary - fieldName naming rules via collections/fields/add (strategy 2)
Constraint: milvus_type_field_name_rules_001
Endpoint: collections+fields+add
Blindspot: BS-01 Parameter Coercion Trust / BS-04 Boundary Default Optimism
Rule: ^[A-Za-z_][A-Za-z0-9_]*$, <=255. fields+add is a R1-uncovered surface.
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
COLL = "bnd_r2_fadd_" + TS


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

BAD = ["123field", "@field", "my-field", "field name", "f$eld",
       "", None, 123]
accepted = []
for fn in BAD:
    payload = {"collectionName": COLL,
               "schema": {"fieldName": fn, "dataType": "Int64", "nullable": True}}
    st, b, raw = safe_request("POST", "collections+fields+add", payload)
    ok = is_ok(b)
    print("fields+add fieldName=%r -> http=%s ok=%s raw=%s" % (fn, st, ok, raw[:200]))
    if ok:
        accepted.append(fn)

# 256-char name (rule says <=255)
fn256 = "f" + "a" * 255
st, b, raw = safe_request("POST", "collections+fields+add",
                          {"collectionName": COLL,
                           "schema": {"fieldName": fn256, "dataType": "Int64",
                                      "nullable": True}})
print("fields+add 256-char name -> ok=%s raw=%s" % (is_ok(b), raw[:150]))
if is_ok(b):
    accepted.append("len256")

# control: valid name should succeed
st, b, raw = safe_request("POST", "collections+fields+add",
                          {"collectionName": COLL,
                           "schema": {"fieldName": "valid_field",
                                      "dataType": "Int64", "nullable": True}})
print("fields+add valid name -> ok=%s raw=%s" % (is_ok(b), raw[:150]))

if accepted:
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - fields+add accepted "
          "illegal fieldName(s): %r" % accepted)
    cleanup()
    sys.exit(1)
print("VERDICT: NO_DEFECT")
cleanup()
sys.exit(0)
