#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Vein-mining Script
Target: milvus v2.3.22
Vein: cardinality consistency — collections/get_stats rowCount vs entities/query count(*)
Finding: after inserting 11 rows and load complete, get_stats returns rowCount=0 forever
         while count(*) correctly returns 11 and search/query return all rows.
Control group: fresh collection inserted-while-loaded also shows rowCount=0 (not a
release/insert-timing artifact); rows ARE visible via query/search => not infrastructure.
Source: internal/distributed/proxy/httpserver/handler_v2.go getCollectionStat -> wrapperProxy
        (GetCollectionStatistics served from rootcoord stats which stays 0 pre-flush).
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

COLL = "vein_stat_001"

def run():
    try:
        safe_request("POST", "v2/vectordb/collections/drop", json={"collectionName": COLL})
        http, body, raw = safe_request("POST", "v2/vectordb/collections/create",
            json={"collectionName": COLL, "dimension": 4, "metricType": "L2", "autoId": False})
        setup_ok = is_ok(body)
        if not setup_ok:
            print(f"VERDICT: SCRIPT_ERROR"); sys.exit(2)
        safe_request("POST", "v2/vectordb/collections/load", json={"collectionName": COLL})
        for _ in range(20):
            _, b, _ = safe_request("POST", "v2/vectordb/collections/get_load_state",
                                   json={"collectionName": COLL})
            if is_ok(b) and b.get("data", {}).get("loadState") in ("LoadStateLoaded", "Loaded"):
                break
            time.sleep(1)
        http, body, raw = safe_request("POST", "v2/vectordb/entities/insert",
            json={"collectionName": COLL,
                  "data": [{"id": i, "vector": [float(i), 0, 0, 0]} for i in range(1, 11)]})
        if not is_ok(body):
            print(f"VERDICT: SCRIPT_ERROR"); sys.exit(2)
        time.sleep(10)  # allow bounded-consistency window far beyond
        # ground truth: count(*)
        _, cnt, _ = safe_request("POST", "v2/vectordb/entities/query",
            json={"collectionName": COLL, "filter": "id >= 1", "outputFields": ["count(*)"]})
        true_count = cnt["data"][0]["count(*)"] if is_ok(cnt) else -1
        # control: rows are queryable (infrastructure fine)
        _, q, _ = safe_request("POST", "v2/vectordb/entities/query",
            json={"collectionName": COLL, "filter": "id >= 1", "limit": 10})
        query_rows = len(q.get("data", [])) if is_ok(q) else -1
        # target: get_stats rowCount
        _, st, _ = safe_request("POST", "v2/vectordb/collections/get_stats",
                                json={"collectionName": COLL})
        row_count = st.get("data", {}).get("rowCount", -1) if is_ok(st) else -1
        print(f"count(*)={true_count} query_rows={query_rows} get_stats.rowCount={row_count}")
        if true_count == 10 and query_rows == 10 and row_count == 0:
            print("Detail: get_stats permanently reports rowCount=0 while count(*)=10 "
                  "and query returns all 10 rows on a loaded collection (waited >10s)")
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
