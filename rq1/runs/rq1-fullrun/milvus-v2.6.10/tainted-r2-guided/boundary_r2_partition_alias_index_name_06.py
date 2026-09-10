#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script (R2)
Target: milvus v2.6.10 (REST v2 /v2/vectordb)
Attack: type boundary - resource naming rules for partition / alias / index names (strategy 2)
Constraint: milvus_type_field_name_rules_001 (naming rules family, R1-uncovered surfaces)
Endpoints: partitions+create, aliases+create, indexes+create
Blindspot: BS-04 Boundary Default Optimism
limitations.md naming rules apply to all resources: ^[A-Za-z_][A-Za-z0-9_]*$, <=255.
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
COLL = "bnd_r2_resn_" + TS


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
    for payload in ({"aliasNames": ["1bad", "@bad", "my-bad", "bad name", "b$d"],
                     "collectionName": COLL},):
        try:
            safe_request("POST", "aliases+drop", {"collectionName": COLL, "aliasName": n})
        except Exception:
            pass
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

BAD = ["1bad", "@bad", "my-bad", "bad name", "b$d"]
accepted = []

# partitions
for n in BAD:
    st, b, raw = safe_request("POST", "partitions+create",
                              {"collectionName": COLL, "partitionName": n})
    ok = is_ok(b)
    print("partitions+create %r -> ok=%s raw=%s" % (n, ok, raw[:160]))
    if ok:
        accepted.append(("partition", n))

# aliases
for n in BAD:
    st, b, raw = safe_request("POST", "aliases+create",
                              {"collectionName": COLL, "aliasName": n})
    ok = is_ok(b)
    print("aliases+create %r -> ok=%s raw=%s" % (n, ok, raw[:160]))
    if ok:
        accepted.append(("alias", n))

# indexes (indexName optional; supply illegal names)
for n in BAD:
    st, b, raw = safe_request("POST", "indexes+create", {
        "collectionName": COLL,
        "indexParams": [{"fieldName": "vec", "indexName": n,
                         "metricType": "L2",
                         "params": {"index_type": "FLAT"}}]})
    ok = is_ok(b)
    print("indexes+create %r -> ok=%s raw=%s" % (n, ok, raw[:160]))
    if ok:
        accepted.append(("index", n))

# controls: valid names should succeed
st, b, raw = safe_request("POST", "partitions+create",
                          {"collectionName": COLL, "partitionName": "valid_p"})
print("control partition valid_p -> ok=%s" % is_ok(b))

if accepted:
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) - illegal resource names "
          "accepted: %r" % (accepted,))
    cleanup()
    sys.exit(1)
print("VERDICT: NO_DEFECT")
cleanup()
sys.exit(0)
