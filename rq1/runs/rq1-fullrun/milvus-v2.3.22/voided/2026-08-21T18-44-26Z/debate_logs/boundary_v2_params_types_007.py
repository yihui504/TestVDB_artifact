#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.3.22
Attack: v2 search params map must be numeric (string->float64); non-numeric values
Constraint: milvus_type_v2_search_001
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
COLL = "bnd_par007"

def wait_loaded(name, tries=20):
    for _ in range(tries):
        http, body, raw = safe_request("POST", "v2/vectordb/collections/get_load_state",
                                       json={"collectionName": name})
        if is_ok(body) and body.get("data", {}).get("loadState") == "Loaded":
            return True
        time.sleep(1)
    return False

def run():
    try:
        safe_request("POST", "v2/vectordb/collections/drop", json={"collectionName": COLL})
        http, body, raw = safe_request("POST", "v2/vectordb/collections/create",
                                       json={"collectionName": COLL, "dimension": 8})
        if not is_ok(body):
            print("VERDICT: SCRIPT_ERROR — create failed: %s" % str(raw)[:150])
            return
        wait_loaded(COLL)
        safe_request("POST", "v2/vectordb/entities/insert",
                    json={"collectionName": COLL, "data": [{"vector": [0.1] * 8}]})

        bad_params = [
            {"level": "not-a-number-str"},      # string value for numeric map
            {"level": None},
            {"level": [1, 2]},
            {"level": {"nested": 1}},
            {"level": True},                    # bool is not float64
        ]
        for p in bad_params:
            http, body, raw = safe_request("POST", "v2/vectordb/entities/search",
                                           json={"collectionName": COLL,
                                                 "data": [[0.1] * 8], "limit": 3, "params": p})
            print("[params=%s] http=%s body=%s" % (p, http, str(raw)[:200]))
            if http >= 500:
                DEFECTS.append("params=%s: Type3 HTTP %s" % (p, http))
            elif http == 200 and is_ok(body):
                DEFECTS.append("params=%s: Type1_IllegalSuccess (non-numeric accepted)" % p)

        # control: numeric value accepted
        http, body, raw = safe_request("POST", "v2/vectordb/entities/search",
                                       json={"collectionName": COLL,
                                             "data": [[0.1] * 8], "limit": 3,
                                             "params": {"radius": 0.5, "range_filter": 0.9}})
        print("[numeric control] http=%s body=%s" % (http, str(raw)[:250]))
        if not is_ok(body):
            DEFECTS.append("numeric params control rejected: %s" % str(raw)[:150])
    finally:
        try:
            safe_request("POST", "v2/vectordb/collections/drop", json={"collectionName": COLL})
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
