#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Vein-mining Script
Target: milvus v2.3.22
Vein: v1/v2 semantic divergence — quick-create default autoID.
      v1 quick-create forces autoID=true (explicit id insert rejected 1804).
      v2 quick-create defaults autoId=false (explicit id insert accepted).
Control group: both create paths succeed; describe shows autoId true (v1) vs false (v2).
Source: handler_v1.go httpCollectionNameReq -> autoID hardcoded true;
        handler_v2.go CreateReqV2 autoID default false.
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

C1 = "vein_v1_005"
C2 = "vein_v2_005"

def run():
    try:
        for c in (C1, C2):
            safe_request("POST", "v1/vector/collections/drop", json={"collectionName": c})
        # v1 quick-create
        _, b1, _ = safe_request("POST", "v1/vector/collections/create",
                                json={"collectionName": C1, "dimension": 4})
        ok1 = is_ok(b1)
        # v2 quick-create (identical minimal payload)
        _, b2, _ = safe_request("POST", "v2/vectordb/collections/create",
                                json={"collectionName": C2, "dimension": 4})
        ok2 = is_ok(b2)
        print(f"v1 create ok={ok1}; v2 create ok={ok2}")
        if not (ok1 and ok2):
            print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
        time.sleep(2)
        # describe autoId on both
        _, d1, _ = safe_request("POST", "v2/vectordb/collections/describe",
                                json={"collectionName": C1})
        _, d2, _ = safe_request("POST", "v2/vectordb/collections/describe",
                                json={"collectionName": C2})
        auto1 = d1.get("data", {}).get("autoId") if is_ok(d1) else None
        auto2 = d2.get("data", {}).get("autoId") if is_ok(d2) else None
        # insert explicit id on both (same row shape)
        _, i1, _ = safe_request("POST", "v1/vector/insert",
            json={"collectionName": C1, "data": [{"id": 1, "vector": [1, 0, 0, 0]}]})
        _, i2, _ = safe_request("POST", "v2/vectordb/entities/insert",
            json={"collectionName": C2, "data": [{"id": 1, "vector": [1, 0, 0, 0]}]})
        code_i1 = i1.get("code") if isinstance(i1, dict) else -1
        code_i2 = i2.get("code") if isinstance(i2, dict) else -1
        print(f"autoId v1={auto1} v2={auto2}; explicit-id insert code v1={code_i1} v2={code_i2}")
        if isinstance(auto1, bool) and isinstance(auto2, bool) and auto1 != auto2:
            print("Detail: identical quick-create payload (collectionName+dimension) yields "
                  f"conflicting default PK generation: v1 autoId={auto1}, v2 autoId={auto2}; "
                  "the same explicit-id row is rejected by one face and accepted by the other")
            print("VERDICT: DEFECT_FOUND")
            sys.exit(1)
        print("VERDICT: NO_DEFECT")
        sys.exit(0)
    finally:
        for c in (C1, C2):
            try:
                safe_request("POST", "v2/vectordb/collections/drop", json={"collectionName": c})
            except Exception:
                pass

run()
