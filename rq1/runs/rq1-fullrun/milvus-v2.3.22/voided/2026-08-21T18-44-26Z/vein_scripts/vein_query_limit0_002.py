#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Vein-mining Script
Target: milvus v2.3.22
Vein: pagination_cursor — limit=0 on query should mean "return zero rows" (or be rejected),
      but v2/v1 query silently treat limit 0 as "no limit" returning ALL rows (11).
Control group: limit=1 returns 1 row, offset=5 limit=1 returns row 6 -> limit param is
        honored for non-zero values; only limit=0 silently means unlimited.
Source: handler_v2.go query(): `if httpReq.Limit > 0 && ...` — limit<=0 param never sent,
        so limit=0 becomes unbounded query. Same for v1.
"""
import requests, json, sys, os, time

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

COLL = "vein_lim_002"

def run():
    try:
        safe_request("POST", "v2/vectordb/collections/drop", json={"collectionName": COLL})
        http, body, raw = safe_request("POST", "v2/vectordb/collections/create",
            json={"collectionName": COLL, "dimension": 4, "metricType": "L2", "autoId": False})
        if not is_ok(body):
            print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
        safe_request("POST", "v2/vectordb/collections/load", json={"collectionName": COLL})
        for _ in range(20):
            _, b, _ = safe_request("POST", "v2/vectordb/collections/get_load_state",
                                   json={"collectionName": COLL})
            if is_ok(b) and b.get("data", {}).get("loadState") in ("LoadStateLoaded", "Loaded"):
                break
            time.sleep(1)
        _, b, _ = safe_request("POST", "v2/vectordb/entities/insert",
            json={"collectionName": COLL,
                  "data": [{"id": i, "vector": [float(i), 0, 0, 0]} for i in range(1, 12)]})
        if not is_ok(b):
            print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
        time.sleep(5)
        # control: limit=1 honored
        _, q1, _ = safe_request("POST", "/".join(["v2", "vectordb", "entities", "query"]),
            json={"collectionName": COLL, "filter": "id >= 1", "limit": 1})
        n1 = len(q1.get("data", [])) if is_ok(q1) else -1
        # target: limit=0
        _, q0, _ = safe_request("POST", "v2/vectordb/entities/query",
            json={"collectionName": COLL, "filter": "id >= 1", "limit": 0})
        code0 = q0.get("code") if isinstance(q0, dict) else -1
        n0 = len(q0.get("data", [])) if is_ok(q0) else -1
        print(f"control limit=1 -> {n1} rows; limit=0 -> code={code0}, {n0} rows")
        if n1 == 1 and is_ok(q0) and n0 == 11:
            print("Detail: limit=0 silently treated as unbounded: returns all 11 rows "
                  "instead of 0 rows or a rejection (search limit=0 IS rejected -> "
                  "inconsistent limit semantics between query and search)")
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
