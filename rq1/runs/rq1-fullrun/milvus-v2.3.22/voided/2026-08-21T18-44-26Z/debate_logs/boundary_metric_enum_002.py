#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.3.22
Attack: metricType enum boundary (v1 + v2 create)
Constraint: milvus_type_create_collection_001 (metricType in 7-value enum)
"""
import requests, json, sys, os

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

def drop(name):
    try:
        safe_request("POST", "v1/vector/collections/drop", json={"collectionName": name})
    except Exception:
        pass

def create_v1(name, dim, metric):
    drop(name)
    return safe_request("POST", "v1/vector/collections/create",
                        json={"collectionName": name, "dimension": dim, "metricType": metric})

def create_v2(name, dim, metric):
    drop(name)
    return safe_request("POST", "v2/vectordb/collections/create",
                        json={"collectionName": name, "dimension": dim, "metricType": metric})

def run():
    # illegal metric values across both API faces
    bad = ["l2", "cosine", "euclidean", "", "L3", "HAMMING ", 123, None, "L2;DROP"]
    for i, m in enumerate(bad):
        name = "bnd_met002_v1_%d" % i
        http, body, raw = create_v1(name, 8, m)
        print("[v1 metric=%r] http=%s body=%s" % (m, http, str(raw)[:200]))
        if http >= 500:
            DEFECTS.append("v1 metric=%r: Type3 HTTP %s" % (m, http))
        elif http == 200 and is_ok(body):
            DEFECTS.append("v1 metric=%r: Type1_IllegalSuccess" % m)
        drop(name)
        name2 = "bnd_met002_v2_%d" % i
        http, body, raw = create_v2(name2, 8, m)
        print("[v2 metric=%r] http=%s body=%s" % (m, http, str(raw)[:200]))
        if http >= 500:
            DEFECTS.append("v2 metric=%r: Type3 HTTP %s" % (m, http))
        elif http == 200 and is_ok(body):
            DEFECTS.append("v2 metric=%r: Type1_IllegalSuccess" % m)
        drop(name2)
    # control: legal metric via v1, read back metric via v1 describe (v1 default L2)
    http, body, raw = create_v1("bnd_met002_ok", 8, "IP")
    print("[v1 metric=IP control] http=%s" % http)
    if not is_ok(body):
        DEFECTS.append("control IP rejected: %s" % str(raw)[:120])
    else:
        d_http, d_body, d_raw = safe_request("GET", "v1/vector/collections/describe",
                                             params={"collectionName": "bnd_met002_ok"})
        print("[readback] %s" % str(d_raw)[:300])
        if "IP" not in str(d_raw):
            DEFECTS.append("readback: metric IP not visible in describe (silent drop?)")
    drop("bnd_met002_ok")

if __name__ == "__main__":
    run()
    if DEFECTS:
        for d in DEFECTS:
            print("DEFECT:", d)
        print("VERDICT: DEFECT_FOUND")
    else:
        print("VERDICT: NO_DEFECT")
