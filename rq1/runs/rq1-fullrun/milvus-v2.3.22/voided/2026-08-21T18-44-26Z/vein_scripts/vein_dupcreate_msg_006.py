#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Vein-mining Script
Target: milvus v2.3.22
Vein: v1/v2 divergence + error attribution — duplicate create of an EXISTING
      collection with IDENTICAL parameters:
      v2 -> silent success code 200; v1 -> code 65535 'create duplicate collection
      with different parameters'. Two REST faces of the same operation disagree.
      Additionally, an immediate re-create (before auto-index settles) surfaces a
      misleading 'CreateIndex failed: at most one distinct index is allowed per
      field' error instead of the duplicate-collection cause.
Control group: dup create with DIFFERENT params correctly errors on both faces
        ('duplicate ... different parameters'), so v2 CAN detect duplicates.
Source: handler_v2.go create(): CreateCollection treats identical-dup as success,
        then auto CreateIndex races/fails; handler_v1.go always errors.
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

COLL = "vein_dup_006"

def run():
    try:
        safe_request("POST", "v2/vectordb/collections/drop", json={"collectionName": COLL})
        _, b, _ = safe_request("POST", "v2/vectordb/collections/create",
            json={"collectionName": COLL, "dimension": 4, "metricType": "L2", "autoId": False})
        if not is_ok(b):
            print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
        # control: dup with different params must error on both faces
        _, c2, _ = safe_request("POST", "v2/vectordb/collections/create",
            json={"collectionName": COLL, "dimension": 8, "metricType": "L2", "autoId": False})
        _, c1, _ = safe_request("POST", "v1/vector/collections/create",
                                json={"collectionName": COLL, "dimension": 8})
        ctrl_ok = (not is_ok(c2)) and (not is_ok(c1))
        time.sleep(5)  # let auto-index settle
        # target: identical duplicate create
        _, d2, _ = safe_request("POST", "v2/vectordb/collections/create",
            json={"collectionName": COLL, "dimension": 4, "metricType": "L2", "autoId": False})
        code2 = d2.get("code") if isinstance(d2, dict) else -1
        _, d1, _ = safe_request("POST", "v1/vector/collections/create",
                                json={"collectionName": COLL, "dimension": 4})
        code1 = d1.get("code") if isinstance(d1, dict) else -1
        msg1 = (d1.get("message") or "") if isinstance(d1, dict) else ""
        print(f"ctrl diff-param dup rejected: v2={not is_ok(c2)} v1={not is_ok(c1)}")
        print(f"identical dup: v2 code={code2}, v1 code={code1} ({msg1[:70]!r})")
        if ctrl_ok and is_ok(d2) and (not is_ok(d1)) and "duplicate" in msg1.lower():
            print("Detail: identical duplicate create silently succeeds (code 200) on v2 "
                  "face while v1 face correctly rejects with 'create duplicate collection' "
                  "— same operation, two faces, contradictory outcomes; v2 proves it can "
                  "detect dups (diff-param case errors)")
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
