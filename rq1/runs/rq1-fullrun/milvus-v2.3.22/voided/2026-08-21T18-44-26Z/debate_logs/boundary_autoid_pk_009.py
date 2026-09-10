#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.3.22
Attack: autoID PK policy — v1 insert with explicit id must fail 1804; upsert on autoID rejected;
        v2 explicit schema (autoID=false) insert without id must fail
Constraints: milvus_state_insert_001, milvus_state_upsert_001, milvus_state_v2_create_001
"""
import requests, json, sys, os, time

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
V1 = "bnd_pk009_v1"
V2 = "bnd_pk009_v2"

def wait_loaded(name, tries=20):
    for _ in range(tries):
        http, body, raw = safe_request("POST", "v2/vectordb/collections/get_load_state",
                                       json={"collectionName": name})
        if is_ok(body) and body.get("data", {}).get("loadState") == "Loaded":
            return True
        time.sleep(1)
    return False

def run():
    try:
        # --- v1 quick-create: autoID=true forced ---
        safe_request("POST", "v1/vector/collections/drop", json={"collectionName": V1})
        http, body, raw = safe_request("POST", "v1/vector/collections/create",
                                       json={"collectionName": V1, "dimension": 8})
        if not is_ok(body):
            print("VERDICT: SCRIPT_ERROR — v1 create failed: %s" % str(raw)[:150])
            return
        wait_loaded(V1)

        # explicit id insert -> must fail 1804
        http, body, raw = safe_request("POST", "v1/vector/insert",
                                       json={"collectionName": V1,
                                             "data": [{"id": 1, "vector": [0.1] * 8}]})
        print("[v1 insert explicit id] http=%s body=%s" % (http, str(raw)[:250]))
        if http >= 500:
            DEFECTS.append("v1 insert explicit id: Type3 HTTP %s" % http)
        elif http == 200 and is_ok(body):
            DEFECTS.append("v1 insert explicit id: Type1_IllegalSuccess (autoID=true bypassed)")

        # upsert on autoID collection -> must be rejected
        http, body, raw = safe_request("POST", "v1/vector/upsert",
                                       json={"collectionName": V1,
                                             "data": [{"vector": [0.1] * 8}]})
        print("[v1 upsert autoID] http=%s body=%s" % (http, str(raw)[:250]))
        if http >= 500:
            DEFECTS.append("v1 upsert autoID: Type3 HTTP %s" % http)
        elif http == 200 and is_ok(body):
            DEFECTS.append("v1 upsert autoID: Type1_IllegalSuccess (upsert allowed)")

        # control: insert without id succeeds
        http, body, raw = safe_request("POST", "v1/vector/insert",
                                       json={"collectionName": V1, "data": [{"vector": [0.1] * 8}]})
        print("[v1 insert no id control] http=%s" % http)
        if not is_ok(body):
            DEFECTS.append("v1 insert no id control failed: %s" % str(raw)[:120])

        # --- v2 explicit schema: autoID default false ---
        safe_request("POST", "v2/vectordb/collections/drop", json={"collectionName": V2})
        schema = {"fields": [
            {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
            {"fieldName": "vector", "dataType": "FloatVector",
             "elementTypeParams": {"dim": 8}},
        ]}
        http, body, raw = safe_request("POST", "v2/vectordb/collections/create",
                                       json={"collectionName": V2, "schema": schema})
        print("[v2 schema create] http=%s body=%s" % (http, str(raw)[:200]))
        if not is_ok(body):
            print("VERDICT: SCRIPT_ERROR — v2 schema create failed: %s" % str(raw)[:150])
            return
        safe_request("POST", "v2/vectordb/collections/load", json={"collectionName": V2})
        wait_loaded(V2)

        # insert without PK on autoID=false -> must fail
        http, body, raw = safe_request("POST", "v2/vectordb/entities/insert",
                                       json={"collectionName": V2,
                                             "data": [{"vector": [0.1] * 8}]})
        print("[v2 insert no id (autoID=false)] http=%s body=%s" % (http, str(raw)[:250]))
        if http >= 500:
            DEFECTS.append("v2 insert no id: Type3 HTTP %s" % http)
        elif http == 200 and is_ok(body):
            DEFECTS.append("v2 insert no id: Type1_IllegalSuccess (PK silently generated?)")

        # read-back: describe v2 schema should show autoID=false
        http, body, raw = safe_request("POST", "v2/vectordb/collections/describe",
                                       json={"collectionName": V2})
        print("[v2 describe readback] %s" % str(raw)[:400])
        if "autoID" in str(raw):
            if '"autoID": true' in str(raw).replace("'", '"'):
                DEFECTS.append("v2 describe: autoID=true persisted for explicit schema (default violated)")

        # control: insert with PK succeeds
        http, body, raw = safe_request("POST", "v2/vectordb/entities/insert",
                                       json={"collectionName": V2,
                                             "data": [{"id": 42, "vector": [0.1] * 8}]})
        print("[v2 insert id=42 control] http=%s body=%s" % (http, str(raw)[:150]))
        if not is_ok(body):
            DEFECTS.append("v2 insert with id control failed: %s" % str(raw)[:120])
    finally:
        for c in (V1, V2):
            try:
                safe_request("POST", "v1/vector/collections/drop", json={"collectionName": c})
            except Exception:
                pass

if __name__ == "__main__":
    run()
    if DEFECTS:
        for d in DEFECTS:
            print("DEFECT:", d)
        print("VERDICT: DEFECT_FOUND")
    else:
        print("VERDICT: NO_DEFECT")
