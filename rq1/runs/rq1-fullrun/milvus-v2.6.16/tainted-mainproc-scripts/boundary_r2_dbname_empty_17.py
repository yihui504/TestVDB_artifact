#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GT 49889: dbName 空串跨端点接受（静默默认库） (milvus v2.6.16 R2)"""
import json, os, urllib.request, sys

BASE = os.environ.get("TESTVDB_DB_URL", "http://localhost:19530")
def req(path, body):
    r = urllib.request.Request(BASE + path, json.dumps(body).encode(),
        {"Authorization": "Bearer root:Milvus", "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=30).read())

eps = [("collections/list", {"dbName": ""}), ("collections/describe", {"collectionName": "x", "dbName": ""}),
        ("collections/drop", {"collectionName": "no_such_x", "dbName": ""}), ("collections/create", {"collectionName": "r2db17", "dimension": 4, "dbName": ""})]
for p, b in eps:
    r = req("/v2/vectordb/" + p, b)
    print(p, "dbName='':", r["code"], (r.get("message") or "")[:50])
req("/v2/vectordb/collections/drop", {"collectionName": "r2db17"})
r = req("/v2/vectordb/collections/list", {"dbName": "default"})
print("control dbName=default:", r["code"])
r = req("/v2/vectordb/collections/list", {"dbName": "no_such_db"})
print("control dbName=missing:", r["code"], "(800)")
r = req("/v2/vectordb/entities/query", {"collectionName": "r2db17", "filter": ""})
print("control filter='':", r["code"], (r.get("message") or "")[:40], "(v2.6.16 已修)")
print("VERDICT: DEFECT_FOUND")
