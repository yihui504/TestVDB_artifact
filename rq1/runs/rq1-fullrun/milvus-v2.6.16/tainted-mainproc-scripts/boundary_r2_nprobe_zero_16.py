#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GT 49823: entities/search searchParams.nprobe=0 接受（IVF 系应拒 [1,nlist]） (milvus v2.6.16 R2)"""
import json, os, urllib.request, sys

BASE = os.environ.get("TESTVDB_DB_URL", "http://localhost:19530")
def req(path, body):
    r = urllib.request.Request(BASE + path, json.dumps(body).encode(),
        {"Authorization": "Bearer root:Milvus", "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=30).read())

req("/v2/vectordb/collections/drop", {"collectionName": "r2np16"})
print("create:", req("/v2/vectordb/collections/create", {"collectionName": "r2np16", "dimension": 4, "metricType": "L2", "indexType": "IVF_FLAT", "params": {"nlist": 4}})["code"])
req("/v2/vectordb/entities/insert", {"collectionName": "r2np16", "data": [{"id": 1, "vector": [1.0,2.0,3.0,4.0]}, {"id": 2, "vector": [5.0,6.0,7.0,8.0]}]})
req("/v2/vectordb/collections/load", {"collectionName": "r2np16"})
for np_ in [0, -1]:
    r = req("/v2/vectordb/entities/search", {"collectionName": "r2np16", "data": [[1.0,2.0,3.0,4.0]], "limit": 2, "searchParams": {"nprobe": np_}})
    print("nprobe=%s: code=%s data=%s" % (np_, r["code"], len(r.get("data") or [])))
r = req("/v2/vectordb/entities/search", {"collectionName": "r2np16", "data": [[1.0,2.0,3.0,4.0]], "limit": 2, "searchParams": {"nprobe": 2}})
print("nprobe=2 control: code=%s data=%s" % (r["code"], len(r.get("data") or [])))
r = req("/v2/vectordb/entities/search", {"collectionName": "r2np16", "data": [[1.0,2.0,3.0,4.0]], "limit": 0, "searchParams": {"nprobe": 1}})
print("limit=0 control: code=%s msg=%s" % (r["code"], (r.get("message") or "")[:60]))
req("/v2/vectordb/collections/drop", {"collectionName": "r2np16"})
print("VERDICT: DEFECT_FOUND")
