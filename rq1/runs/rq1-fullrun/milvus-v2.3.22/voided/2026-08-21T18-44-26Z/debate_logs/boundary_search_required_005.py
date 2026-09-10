#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.3.22
Attack: v1 search required params (collectionName/vector) + type confusion on vector
Constraint: milvus_range_search_001, milvus_type_v1_search_001
"""
import requests, json, sys, os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = os.environ.get("TESTVDB_DB_URL", "http://localhost:19530").rstrip("/")
AUTH = os.environ.get("TESTVDB_AUTH_HEADER", "Bearer root:Milvus")

def safe_request(method, path, **kw):
    url = BASE_URL + "/" + path.lstrip("/")
    headers = kw.pop("headers", {}) or {}
    if AUTH:
        headers["Authorization"] = AUTH
    headers.setdefault("Content-Type", "application/json")
    try:
        r = requests.request(method, url, headers=headers, timeout=kw.pop("timeout", 60), **kw)
    except Exception as e:
        return 0, None, repr(e)
    try:
        return r.status_code, r.json(), r.text
    except Exception:
        return r.status_code, None, r.text

def is_ok(b):
    return isinstance(b, dict) and b.get("code") == 200

DEFECTS = []

def run():
    # missing vector
    http, body, raw = safe_request("POST", "v1/vector/search",
                                   json={"collectionName": "whatever", "limit": 3})
    print("[missing vector] http=%s body=%s" % (http, str(raw)[:200]))
    if http == 200 and is_ok(body):
        DEFECTS.append("missing vector: Type1_IllegalSuccess")
    # missing collectionName
    http, body, raw = safe_request("POST", "v1/vector/search",
                                   json={"vector": [0.1] * 8, "limit": 3})
    print("[missing collectionName] http=%s body=%s" % (http, str(raw)[:200]))
    if http == 200 and is_ok(body):
        DEFECTS.append("missing collectionName: Type1_IllegalSuccess")
    # vector type confusions
    cases = [
        ("vector=flat array of str", {"collectionName": "x", "vector": ["0.1"] * 8}),
        ("vector=string", {"collectionName": "x", "vector": "0.1,0.2"}),
        ("vector=null", {"collectionName": "x", "vector": None}),
        ("vector=empty []", {"collectionName": "x", "vector": []}),
        ("vector=nested [[..]]", {"collectionName": "x", "vector": [[0.1] * 8]}),
        ("vector=number", {"collectionName": "x", "vector": 8}),
        ("vector with NaN str", {"collectionName": "x", "vector": [0.1, "NaN", 0.2] * 3}),
    ]
    for case, payload in cases:
        payload.setdefault("limit", 3)
        http, body, raw = safe_request("POST", "v1/vector/search", json=payload)
        print("[%s] http=%s body=%s" % (case, http, str(raw)[:200]))
        if http >= 500:
            DEFECTS.append("%s: Type3 HTTP %s" % (case, http))
        elif http == 200 and is_ok(body):
            DEFECTS.append("%s: Type1_IllegalSuccess" % case)

    # Accept-Type-Allow-Int64: header toggles int64 id encoding (default string)
    # create + insert, then search with and without header, compare id types
    COLL = "bnd_req005"
    try:
        safe_request("POST", "v1/vector/collections/drop", json={"collectionName": COLL})
        safe_request("POST", "v1/vector/collections/create",
                     json={"collectionName": COLL, "dimension": 8})
        http, body, raw = safe_request("POST", "v1/vector/insert",
                                       json={"collectionName": COLL, "data": [{"vector": [0.1] * 8}]})
        print("[setup insert] %s" % str(raw)[:120])
        h1, b1, r1 = safe_request("POST", "v1/vector/search",
                                  json={"collectionName": COLL, "vector": [0.1] * 8, "limit": 1})
        h2, b2, r2 = safe_request("POST", "v1/vector/search",
                                  json={"collectionName": COLL, "vector": [0.1] * 8, "limit": 1},
                                  headers={"Accept-Type-Allow-Int64": "true"})
        print("[default ids] %s" % str(r1)[:250])
        print("[int64 hdr ids] %s" % str(r2)[:250])
        try:
            id_default = b1["data"][0].get("id")
            id_int64 = b2["data"][0].get("id")
            print("[id types] default=%r(%s) header=%r(%s)"
                  % (id_default, type(id_default).__name__, id_int64, type(id_int64).__name__))
            # contract: default string, header true -> number
            if not isinstance(id_default, str):
                DEFECTS.append("Accept-Type-Allow-Int64: default id should be string, got %s"
                               % type(id_default).__name__)
            if not isinstance(id_int64, int):
                DEFECTS.append("Accept-Type-Allow-Int64: header id should be number, got %s"
                               % type(id_int64).__name__)
        except Exception as e:
            print("[id compare skipped] %r" % e)
    finally:
        try:
            safe_request("POST", "v1/vector/collections/drop", json={"collectionName": COLL})
        except Exception:
            pass

if __name__ == "__main__":
    run()
    if DEFECTS:
        for d in DEFECTS:
            print("DEFECT:", d)
        print("VERDICT: DEFECT_FOUND")
    else:
        print("VERDICT: NO_DEFECT")
