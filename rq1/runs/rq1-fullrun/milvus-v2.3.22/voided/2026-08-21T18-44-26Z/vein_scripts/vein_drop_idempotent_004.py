#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Vein-mining Script
Target: milvus v2.3.22
Vein: state-machine invariant — dropping a NON-EXISTENT collection succeeds (code 200).
Control group: load on nonexistent collection correctly errors code 100; search errors.
        Only drop is idempotent-success, hiding typos (e.g. dropping 'vein_a ' with a
        trailing space silently 'succeeds' while the real collection survives).
Source: proxy DropCollection treats NotFound as success.
"""
import requests, json, sys, os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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

COLL = "vein_drp_004"
GHOST = "vein_drp_004_ghost"

def run():
    try:
        safe_request("POST", "v2/vectordb/collections/drop", json={"collectionName": COLL})
        _, b, _ = safe_request("POST", "v2/vectordb/collections/create",
            json={"collectionName": COLL, "dimension": 4, "metricType": "L2", "autoId": False})
        if not is_ok(b):
            print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
        # control: load on nonexistent -> error
        _, cl, _ = safe_request("POST", "v2/vectordb/collections/load",
                                json={"collectionName": GHOST})
        code_load = cl.get("code") if isinstance(cl, dict) else -1
        # target: drop nonexistent
        _, cd, _ = safe_request("POST", "v2/vectordb/collections/drop",
                                json={"collectionName": GHOST})
        code_drop = cd.get("code") if isinstance(cd, dict) else -1
        print(f"load nonexistent code={code_load}; drop nonexistent code={code_drop}")
        if code_load != 200 and code_drop == 200:
            print("Detail: drop of nonexistent collection returns success code 200 while "
                  "load/search correctly report not-found; typo'd drop silently 'succeeds'")
            print("VERDICT: DEFECT_FOUND")
            sys.exit(1)
        print("VERDICT: NO_DEFECT")
        sys.exit(0)
    finally:
        try:
            safe_request("POST", "v2/vectordb/collections/drop", json={"collectionName": COLL})
        except Exception:
            pass

run()
