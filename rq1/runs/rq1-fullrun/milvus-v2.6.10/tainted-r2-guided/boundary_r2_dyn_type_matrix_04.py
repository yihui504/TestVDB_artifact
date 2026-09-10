#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script (R2)
Target: milvus v2.6.10 (REST v2 /v2/vectordb)
Attack: type boundary - dynamic field TYPE consistency via entities/insert (strategy 2)
Constraint: milvus_type_dynamic_field_consistency_001
Endpoint: entities+insert
Blindspot: BS-01 Parameter Coercion Trust
Matrix: first insert establishes dynamic field type; second insert with incompatible
type for the SAME field must be rejected (code 1100). Full cross-type matrix.
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


def cleanup(coll):
    try:
        safe_request("POST", "collections+drop", {"collectionName": coll})
    except Exception:
        pass


def make_coll(coll):
    st, b, raw = safe_request("POST", "collections+create", {
        "collectionName": coll,
        "schema": {
            "enableDynamicField": True,
            "fields": [
                {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
                {"fieldName": "vec", "dataType": "FloatVector",
                 "elementTypeParams": {"dim": DIM}}]}})
    return is_ok(b), raw


# values grouped by JSON-inferred type
VALS = {"string": ["hello", ""], "int": [1, -5], "float": [1.5],
        "bool": [True], "array_str": [["a", "b"]], "array_int": [[1, 2]]}
PAIRS = [("string", "int"), ("int", "string"), ("bool", "int"),
         ("string", "array_str"), ("array_str", "array_int"), ("int", "float")]

defects = []
ci = 0
for t1, t2 in PAIRS:
    ci += 1
    coll = "bnd_r2_dtc_%d_%s" % (ci, TS)
    cleanup(coll)
    ok, raw = make_coll(coll)
    if not ok:
        print("setup failed for %s vs %s: %s" % (t1, t2, raw[:150]))
        continue
    for v1 in VALS[t1]:
        for v2 in VALS[t2]:
            st, b, raw = safe_request("POST", "entities+insert", {
                "collectionName": coll,
                "data": [{"id": 1, "vec": [0.1] * DIM, "dynf": v1}]})
            if not is_ok(b):
                print("first insert %s=%r failed (skip pair): %s" % (t1, v1, raw[:120]))
                continue
            st, b, raw = safe_request("POST", "entities+insert", {
                "collectionName": coll,
                "data": [{"id": 2, "vec": [0.1] * DIM, "dynf": v2}]})
            ok2 = is_ok(b)
            print("dynf %s(%r) -> %s(%r): second insert ok=%s raw=%s"
                  % (t1, v1, t2, v2, ok2, raw[:180]))
            if ok2:
                defects.append("dynf %s->%s accepted (incompatible type switch)" % (t1, t2))
    cleanup(coll)
    if len(defects) >= 3:
        break  # enough evidence

if defects:
    for d in defects:
        print("DEFECT: %s" % d)
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - dynamic field type "
          "consistency not enforced")
    sys.exit(1)
print("VERDICT: NO_DEFECT")
sys.exit(0)
