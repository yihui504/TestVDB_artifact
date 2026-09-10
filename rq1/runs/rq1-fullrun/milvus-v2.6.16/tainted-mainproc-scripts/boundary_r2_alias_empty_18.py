#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GT 50018: aliases/list collectionName 空串接受（其他端点 1802） (milvus v2.6.16 R2)"""
import json, os, urllib.request, sys

BASE = os.environ.get("TESTVDB_DB_URL", "http://localhost:19530")
def req(path, body):
    r = urllib.request.Request(BASE + path, json.dumps(body).encode(),
        {"Authorization": "Bearer root:Milvus", "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=30).read())

req("/v2/vectordb/collections/drop", {"collectionName": "r2al18"})
print("setup create:", req("/v2/vectordb/collections/create", {"collectionName": "r2al18", "dimension": 4})["code"])
print("alias create:", req("/v2/vectordb/aliases/create", {"aliasName": "r2al", "collectionName": "r2al18"})["code"])
r = req("/v2/vectordb/aliases/list", {"collectionName": "", "dbName": "default"})
print("aliases/list collectionName='':", r["code"], "(bug: code 0)")
for p in ["collections/describe", "collections/load"]:
    r = req("/v2/vectordb/" + p, {"collectionName": ""})
    print(p, "collectionName='':", r["code"], (r.get("message") or "")[:45])
r = req("/v2/vectordb/aliases/list", {"collectionName": "r2al18", "dbName": "default"})
print("control 正常名:", r["code"], len(r.get("data") or []))
req("/v2/vectordb/aliases/drop", {"aliasName": "r2al"})
req("/v2/vectordb/collections/drop", {"collectionName": "r2al18"})
print("VERDICT: DEFECT_FOUND")
