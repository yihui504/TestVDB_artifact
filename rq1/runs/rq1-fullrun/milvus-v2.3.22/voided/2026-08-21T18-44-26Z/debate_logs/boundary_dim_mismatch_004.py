#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.3.22
Attack: vector dimension mismatch on insert + search (v1 & v2)
Constraint: behavioral_search_003 (dim mismatch -> 1804), FloatVector data type dim rule
"""
import requests, json, sys, os, time

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
COLL = "bnd_dim004"

def drop(name):
    try:
        safe_request("POST", "v1/vector/collections/drop", json={"collectionName": name})
    except Exception:
        pass

def wait_loaded(name, tries=20):
    for _ in range(tries):
        http, body, raw = safe_request("POST", "v2/vectordb/collections/get_load_state",
                                       json={"collectionName": name})
        if is_ok(body):
            st = body.get("data", {}).get("loadState")
            if st == "Loaded":
                return True
        time.sleep(1)
    return False

def run():
    drop(COLL)
    http, body, raw = safe_request("POST", "v1/vector/collections/create",
                                   json={"collectionName": COLL, "dimension": 8})
    print("[create dim=8] http=%s" % http)
    if not is_ok(body):
        print("VERDICT: SCRIPT_ERROR — control create failed: %s" % str(raw)[:150])
        return
    wait_loaded(COLL)

    # insert with wrong dims (4, 9, 0) — must be rejected (1804 family)
    for dim in (4, 9, 0):
        http, body, raw = safe_request("POST", "v1/vector/insert",
                                       json={"collectionName": COLL,
                                             "data": [{"vector": [0.1] * dim}]})
        print("[insert dim=%d] http=%s body=%s" % (dim, http, str(raw)[:200]))
        if http >= 500:
            DEFECTS.append("insert dim=%d: Type3 HTTP %s" % (dim, http))
        elif http == 200 and is_ok(body):
            DEFECTS.append("insert dim=%d: Type1_IllegalSuccess (mismatch accepted)" % dim)

    # search with wrong dim
    for dim in (4, 9):
        http, body, raw = safe_request("POST", "v1/vector/search",
                                       json={"collectionName": COLL,
                                             "vector": [0.1] * dim, "limit": 3})
        print("[search dim=%d] http=%s body=%s" % (dim, http, str(raw)[:200]))
        if http >= 500:
            DEFECTS.append("search dim=%d: Type3 HTTP %s" % (dim, http))
        elif http == 200 and is_ok(body):
            DEFECTS.append("search dim=%d: Type1_IllegalSuccess (mismatch accepted)" % dim)

    # v2 search with wrong dim and with empty vector []
    http, body, raw = safe_request("POST", "v2/vectordb/entities/search",
                                   json={"collectionName": COLL,
                                         "data": [[0.1] * 4], "limit": 3})
    print("[v2 search dim=4] http=%s body=%s" % (http, str(raw)[:200]))
    if http == 200 and is_ok(body):
        DEFECTS.append("v2 search dim=4: Type1_IllegalSuccess")
    http, body, raw = safe_request("POST", "v2/vectordb/entities/search",
                                   json={"collectionName": COLL, "data": [[]], "limit": 3})
    print("[v2 search empty vector] http=%s body=%s" % (http, str(raw)[:200]))
    if http == 200 and is_ok(body):
        DEFECTS.append("v2 search empty vector: Type1_IllegalSuccess")
    http, body, raw = safe_request("POST", "v2/vectordb/entities/search",
                                   json={"collectionName": COLL, "data": [], "limit": 3})
    print("[v2 search data=[]] http=%s body=%s" % (http, str(raw)[:200]))
    if http == 200 and is_ok(body):
        DEFECTS.append("v2 search data=[]: Type1_IllegalSuccess")

    # control: correct dim insert + search must succeed
    http, body, raw = safe_request("POST", "v1/vector/insert",
                                   json={"collectionName": COLL, "data": [{"vector": [0.1] * 8}]})
    print("[insert dim=8 control] http=%s" % http)
    if not is_ok(body):
        DEFECTS.append("control insert dim=8 failed: %s" % str(raw)[:120])
    http, body, raw = safe_request("POST", "v1/vector/search",
                                   json={"collectionName": COLL, "vector": [0.1] * 8, "limit": 3})
    print("[search dim=8 control] http=%s" % http)
    if not is_ok(body):
        DEFECTS.append("control search dim=8 failed: %s" % str(raw)[:120])
    drop(COLL)

if __name__ == "__main__":
    run()
    if DEFECTS:
        for d in DEFECTS:
            print("DEFECT:", d)
        print("VERDICT: DEFECT_FOUND")
    else:
        print("VERDICT: NO_DEFECT")
