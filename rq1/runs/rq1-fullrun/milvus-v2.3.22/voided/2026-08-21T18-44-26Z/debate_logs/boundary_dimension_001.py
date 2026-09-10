#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.3.22
Attack: boundary values on dimension (v1 quick-create)
Constraint: milvus_range_create_collection_001 (dimension required and non-zero)
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
    txt = r.text
    try:
        return r.status_code, r.json(), txt
    except Exception:
        return r.status_code, None, txt

def is_ok(body):
    return isinstance(body, dict) and body.get("code") == 200

DEFECTS = []

def check(case, http, body, raw, expect):
    print("[%s] http=%s body=%s" % (case, http, str(raw)[:220]))
    if http == 0:
        DEFECTS.append("%s: Type3 connection failure: %s" % (case, str(raw)[:120]))
        return
    if http >= 500:
        DEFECTS.append("%s: Type3_RuntimeFailure HTTP %s" % (case, http))
        return
    rejected = http != 200 or (isinstance(body, dict) and body.get("code") != 200)
    if expect == "reject" and not rejected:
        DEFECTS.append("%s: Type1_IllegalSuccess (accepted illegal value)" % case)
    elif expect == "ok" and not is_ok(body):
        DEFECTS.append("%s: unexpected rejection: %s" % (case, str(raw)[:120]))

def drop(name):
    try:
        safe_request("POST", "v1/vector/collections/drop", json={"collectionName": name})
    except Exception:
        pass

def run():
    base = "bnd_dim001"
    # 1. dimension = 0 (contract: non-zero) -> must reject
    drop(base + "_d0")
    check("dim=0", *safe_request("POST", "v1/vector/collections/create",
                                 json={"collectionName": base + "_d0", "dimension": 0}), "reject")
    # 2. dimension missing -> must reject
    drop(base + "_dm")
    check("dim=missing", *safe_request("POST", "v1/vector/collections/create",
                                       json={"collectionName": base + "_dm"}), "reject")
    # 3. dimension = -8 -> must reject
    drop(base + "_dneg")
    check("dim=-8", *safe_request("POST", "v1/vector/collections/create",
                                  json={"collectionName": base + "_dneg", "dimension": -8}), "reject")
    # 4. dimension = "8" (type confusion string) -> must reject
    drop(base + "_dstr")
    check("dim='8'(string)", *safe_request("POST", "v1/vector/collections/create",
                                           json={"collectionName": base + "_dstr", "dimension": "8"}), "reject")
    # 5. dimension = 8.5 (float truncation confusion) -> must reject
    drop(base + "_dfloat")
    check("dim=8.5", *safe_request("POST", "v1/vector/collections/create",
                                   json={"collectionName": base + "_dfloat", "dimension": 8.5}), "reject")
    # 6. dimension = null -> must reject
    drop(base + "_dnull")
    check("dim=null", *safe_request("POST", "v1/vector/collections/create",
                                    json={"collectionName": base + "_dnull", "dimension": None}), "reject")
    # 7. control: dim=8 -> must succeed, then verify via describe read-back
    drop(base + "_dok")
    check("dim=8(control)", *safe_request("POST", "v1/vector/collections/create",
                                          json={"collectionName": base + "_dok", "dimension": 8}), "ok")
    http, body, raw = safe_request("GET", "v1/vector/collections/describe",
                                   params={"collectionName": base + "_dok"})
    print("[readback] http=%s" % http)
    found_dim = None
    if is_ok(body):
        for f in body.get("data", {}).get("fields", []):
            if f.get("name") == "vector" or f.get("type") in ("FloatVector", 101):
                found_dim = f.get("elementTypeParams", {}).get("dim") or f.get("params", {}).get("dim")
    print("[readback] vector dim persisted = %s (expect 8)" % found_dim)
    if found_dim is not None and str(found_dim) != "8":
        DEFECTS.append("readback: persisted dim=%s != requested 8 (silent coercion)" % found_dim)
    # cleanup
    for s in ("_d0", "_dm", "_dneg", "_dstr", "_dfloat", "_dnull", "_dok"):
        drop(base + s)

if __name__ == "__main__":
    run()
    if DEFECTS:
        for d in DEFECTS:
            print("DEFECT:", d)
        print("VERDICT: DEFECT_FOUND")
    else:
        print("VERDICT: NO_DEFECT")
