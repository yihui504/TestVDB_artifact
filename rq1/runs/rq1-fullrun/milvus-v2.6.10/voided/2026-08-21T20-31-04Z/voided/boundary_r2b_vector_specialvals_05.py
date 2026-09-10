#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script (R2b)
Target: milvus v2.6.10 (REST v2 /v2/vectordb)
Attack: special float values inside FloatVector data (strategy 4)
Constraint: milvus_type_entities_insert_001 (vector rows must be valid)
Endpoints: entities+insert, entities+search
R1 uncovered: NaN / Infinity / -Infinity / huge-magnitude components inside
insert/search vectors, plus mixed int/float components.
"""

import requests
import sys
import os
import time
import math

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
COLL = "bnd_r2b_vsv_" + TS


def safe_request(method, endpoint, payload=None, timeout=90, raw_body=None):
    url = "%s/%s" % (API, endpoint.replace("+", "/"))
    try:
        r = requests.request(method, url,
                             data=raw_body if raw_body is not None else None,
                             json=None if raw_body is not None else payload,
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

defects = []
nan = float("nan")
inf = float("inf")
cases = [
    ("NaN component", [nan] + [0.1] * (DIM - 1)),
    ("Infinity component", [inf] + [0.1] * (DIM - 1)),
    ("-Infinity component", [-inf] + [0.1] * (DIM - 1)),
    ("1e308 magnitude", [1e308] + [0.1] * (DIM - 1)),
    ("mixed int/float", [1] + [0.1] * (DIM - 1)),
    ("boolean component", [True] + [0.1] * (DIM - 1)),
]
import json as _json
for i, (name, vec) in enumerate(cases):
    if any(isinstance(x, float) and (math.isnan(x) or math.isinf(x)) for x in vec):
        # python json= encoder refuses non-finite floats; send raw body with
        # literal NaN/Infinity tokens to probe SERVER-side handling (strategy 7)
        body_txt = _json.dumps({"collectionName": COLL,
                                "data": [{"id": i + 1, "vec": [repr(x) if (math.isnan(x) or math.isinf(x)) else x for x in vec]}]},
                               allow_nan=True)
        st, b, raw = safe_request("POST", "entities+insert", raw_body=body_txt)
    else:
        st, b, raw = safe_request("POST", "entities+insert", {
            "collectionName": COLL, "data": [{"id": i + 1, "vec": vec}]})
    ok = is_ok(b)
    print("insert %s -> http=%s ok=%s raw=%s" % (name, st, ok, raw[:220]))
    if ok and name in ("NaN component", "Infinity component",
                       "-Infinity component"):
        defects.append("insert accepted %s (non-finite float persisted)" % name)
    if st >= 500 or "panic" in raw.lower():
        defects.append("insert %s triggered 5xx/panic: %s" % (name, raw[:150]))

# search with NaN query vector (raw body, literal NaN token)
st, b, raw = safe_request("POST", "entities+search", raw_body=_json.dumps({
    "collectionName": COLL, "data": [[nan] * DIM],
    "annsField": "vec", "limit": 3, "outputFields": ["id"]}, allow_nan=True))
print("search NaN query -> http=%s ok=%s raw=%s" % (st, is_ok(b), raw[:220]))
if st >= 500 or "panic" in raw.lower():
    defects.append("search with NaN query vector triggered 5xx/panic: %s" % raw[:150])

if defects:
    for d in defects:
        print("DEFECT: %s" % d)
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess / non-finite vector values)")
    cleanup()
    sys.exit(1)
print("VERDICT: NO_DEFECT")
cleanup()
sys.exit(0)
