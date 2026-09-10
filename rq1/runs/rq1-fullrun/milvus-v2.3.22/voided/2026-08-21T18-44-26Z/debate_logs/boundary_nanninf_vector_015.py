#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.3.22
Attack: NaN/Infinity vectors in search + insert (JSON non-standard literals via raw body,
        and null-in-vector via normal JSON)
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

def raw_request(path, raw_bytes):
    url = BASE_URL + "/" + path.lstrip("/")
    headers = {"Content-Type": "application/json"}
    if AUTH:
        headers["Authorization"] = AUTH
    try:
        r = requests.post(url, data=raw_bytes, headers=headers, timeout=60)
    except Exception as e:
        return 0, repr(e)
    return r.status_code, r.text

def is_ok(b):
    return isinstance(b, dict) and b.get("code") == 200

DEFECTS = []
COLL = "bnd_nan015"

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
                                       json={"collectionName": COLL, "dimension": 4})
        if not is_ok(body):
            print("VERDICT: SCRIPT_ERROR — create failed: %s" % str(raw)[:150])
            return
        wait_loaded(COLL)

        # NaN / Infinity literals (non-standard JSON) via raw body — Go json rejects these
        for tag, vec in (("NaN", "[NaN, 0.1, 0.2, 0.3]"),
                         ("Infinity", "[Infinity, 0.1, 0.2, 0.3]"),
                         ("-Infinity", "[-Infinity,0.1, 0.2, 0.3]")):
            http, txt = raw_request("v1/vector/search",
                                    ('{"collectionName": "%s", "vector": %s, "limit": 1}'
                                     % (COLL, vec)).encode())
            print("[search vector %s raw] http=%s body=%s" % (tag, http, txt[:200]))
            if http >= 500:
                DEFECTS.append("search %s: Type3 HTTP %s" % (tag, http))

        # null element inside vector (valid JSON, illegal value)
        http, body, raw = safe_request("POST", "v1/vector/search",
                                       json={"collectionName": COLL,
                                             "vector": [None, 0.1, 0.2, 0.3], "limit": 1})
        print("[search vector null elem] http=%s body=%s" % (http, str(raw)[:200]))
        if http >= 500:
            DEFECTS.append("search null elem: Type3 HTTP %s" % http)
        elif http == 200 and is_ok(body):
            DEFECTS.append("search null elem: Type1_IllegalSuccess")

        # string element inside vector
        http, body, raw = safe_request("POST", "v1/vector/search",
                                       json={"collectionName": COLL,
                                             "vector": ["x", 0.1, 0.2, 0.3], "limit": 1})
        print("[search vector str elem] http=%s body=%s" % (http, str(raw)[:200]))
        if http == 200 and is_ok(body):
            DEFECTS.append("search str elem: Type1_IllegalSuccess")

        # insert with null elem
        http, body, raw = safe_request("POST", "v1/vector/insert",
                                       json={"collectionName": COLL,
                                             "data": [{"vector": [0.1, None, 0.2, 0.3]}]})
        print("[insert null elem] http=%s body=%s" % (http, str(raw)[:250]))
        if http >= 500:
            DEFECTS.append("insert null elem: Type3 HTTP %s" % http)
        elif http == 200 and is_ok(body):
            DEFECTS.append("insert null elem: Type1_IllegalSuccess (NaN-typed float stored?)")

        # subnormal / extreme magnitudes should be accepted (behavioral note)
        http, body, raw = safe_request("POST", "v1/vector/insert",
                                       json={"collectionName": COLL,
                                             "data": [{"vector": [1e-45, 1e38, -1e38, 0.0]}]})
        print("[insert extremes control] http=%s body=%s" % (http, str(raw)[:200]))
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
