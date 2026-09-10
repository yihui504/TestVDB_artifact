#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script (R2)
Target: milvus v2.6.10 (REST v2 /v2/vectordb)
Attack: type boundary - dynamic field NAME rules via entities/insert (strategy 2)
Constraint: milvus_type_field_name_rules_001
Endpoint: entities+insert (+entities+query readback)
Blindspot: BS-01 Parameter Coercion Trust
Rule under attack: ^[A-Za-z_][A-Za-z0-9_]*$, len<=255, enforced at insert-time incl dynamic fields.
KEY: insert-time accept + query-time reject = data accessibility defect (write path skips validation).
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
COLL = "bnd_r2_dfn_ins_" + TS


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


# --- setup: full schema with dynamic field enabled ---
st, b, raw = safe_request("POST", "collections+create", {
    "collectionName": COLL,
    "schema": {
        "enableDynamicField": True,
        "fields": [
            {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
            {"fieldName": "vec", "dataType": "FloatVector",
             "elementTypeParams": {"dim": DIM}},
        ]}})
print("create: %s" % raw[:200])
if not is_ok(b):
    print("VERDICT: SCRIPT_ERROR - setup create failed")
    sys.exit(2)
st, b, raw = safe_request("POST", "collections+insert",
                          {"collectionName": COLL,
                           "data": [{"id": 1, "vec": [0.1] * DIM}]})
st, b, raw = safe_request("POST", "collections+load", {"collectionName": COLL})
for _ in range(30):
    if is_ok(b):
        break
    time.sleep(1)
    st, b, raw = safe_request("POST", "collections+load", {"collectionName": COLL})

BAD_NAMES = ["123field", "@field", "my-field", "field name", "f$eld"]
defects = []
for i, fn in enumerate(BAD_NAMES):
    row = {"id": 100 + i, "vec": [0.1] * DIM, fn: "v"}
    st, b, raw = safe_request("POST", "entities+insert",
                              {"collectionName": COLL, "data": [row]})
    accepted = is_ok(b)
    print("insert dyn field %r -> http=%s ok=%s raw=%s" % (fn, st, accepted, raw[:200]))
    if accepted:
        # readback: can query access the illegally-named field?
        st2, b2, raw2 = safe_request("POST", "entities+query", {
            "collectionName": COLL, "filter": "id == %d" % (100 + i),
            "outputFields": [fn]})
        q_ok = is_ok(b2)
        print("  query outputFields=[%r] -> ok=%s raw=%s" % (fn, q_ok, raw2[:200]))
        if not q_ok:
            defects.append("field %r accepted at insert but unreadable at query "
                           "(data accessibility break): %s" % (fn, raw2[:150]))

# boundary: valid 255-char name should work (control)
fn255 = "f" + "a" * 254
st, b, raw = safe_request("POST", "entities+insert",
                          {"collectionName": COLL,
                           "data": [{"id": 200, "vec": [0.1] * DIM, fn255: "v"}]})
print("insert 255-char valid name -> ok=%s raw=%s" % (is_ok(b), raw[:150]))

if defects:
    for d in defects:
        print("DEFECT: %s" % d)
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - %d illegal dynamic field "
          "names accepted at insert" % len(defects))
    cleanup()
    sys.exit(1)
# all rejected at insert = contract enforced
print("VERDICT: NO_DEFECT")
cleanup()
sys.exit(0)
