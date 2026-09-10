#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.3.22
Attack: rowCount consistency (get_stats vs inserted N) + get_load_state on missing
        collection error mapping + describe GET-only (POST -> 404)
Constraints: milvus_inv_count_consistency, milvus_behavioral_describe_002,
             milvus_behavioral_load_state_001
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
COLL = "bnd_stat016"

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
        safe_request("POST", "v1/vector/collections/drop", json={"collectionName": COLL})
        http, body, raw = safe_request("POST", "v1/vector/collections/create",
                                       json={"collectionName": COLL, "dimension": 8})
        if not is_ok(body):
            print("VERDICT: SCRIPT_ERROR — create failed: %s" % str(raw)[:150])
            return
        wait_loaded(COLL)
        # insert 5 rows
        rows = [{"vector": [0.1 * (i + 1)] * 8} for i in range(5)]
        http, body, raw = safe_request("POST", "v1/vector/insert",
                                       json={"collectionName": COLL, "data": rows})
        print("[insert 5] http=%s body=%s" % (http, str(raw)[:150]))
        time.sleep(5)
        http, body, raw = safe_request("POST", "v2/vectordb/collections/get_stats",
                                       json={"collectionName": COLL})
        print("[get_stats] http=%s body=%s" % (http, str(raw)[:200]))
        if is_ok(body):
            try:
                rc = int(body.get("data", {}).get("rowCount"))
                print("[rowCount] %d (expect >=5; exact==5 under strong count)" % rc)
                if rc < 5:
                    DEFECTS.append("rowCount=%d after inserting 5 rows (lost data?)" % rc)
            except Exception:
                DEFECTS.append("rowCount missing/non-numeric: %s" % str(body.get("data"))[:100])
        else:
            DEFECTS.append("get_stats failed: %s" % str(raw)[:120])

        # describe is GET-only: POST -> HTTP 404
        http, body, raw = safe_request("POST", "v1/vector/collections/describe",
                                       json={"collectionName": COLL})
        print("[describe via POST] http=%s body=%s" % (http, str(raw)[:150]))
        if http != 404:
            DEFECTS.append("describe via POST returned HTTP %s (contract: 404 unmatched-route)" % http)

        # describe non-existent -> code 100
        http, body, raw = safe_request("GET", "v1/vector/collections/describe",
                                       params={"collectionName": "bnd_stat016_nope"})
        print("[describe missing] http=%s body=%s" % (http, str(raw)[:200]))
        if http == 200 and isinstance(body, dict):
            if body.get("code") == 200:
                DEFECTS.append("describe missing collection returned code 200 (Type1)")

        # list empty dbName type confusion
        http, body, raw = safe_request("GET", "v1/vector/collections",
                                       params={"dbName": 12345})
        print("[list dbName=12345] http=%s body=%s" % (http, str(raw)[:150]))
        if http >= 500:
            DEFECTS.append("list dbName int: Type3 HTTP %s" % http)
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
