#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.3.22
Attack: idType enum + schema dataType case sensitivity (v2 create)
Constraints: milvus_type_v2_create_collection_001, milvus_type_v2_create_collection_002,
             milvus_type_data_types_001
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
        safe_request("POST", "v2/vectordb/collections/drop", json={"collectionName": name})
    except Exception:
        pass

def run():
    # --- idType enum attacks (quick-create path) ---
    for i, idt in enumerate(["int64", "varchar", "INT64", "Int32", "", 123, None]):
        name = "bnd_idt003_%d" % i
        drop(name)
        http, body, raw = safe_request("POST", "v2/vectordb/collections/create",
                                       json={"collectionName": name, "dimension": 8, "idType": idt})
        print("[idType=%r] http=%s body=%s" % (idt, http, str(raw)[:200]))
        if http >= 500:
            DEFECTS.append("idType=%r: Type3 HTTP %s" % (idt, http))
        elif http == 200 and is_ok(body):
            # accepted — if value not in [Int64, VarChar] exactly, illegal success
            if idt not in ("Int64", "VarChar"):
                DEFECTS.append("idType=%r: Type1_IllegalSuccess (enum violation)" % idt)
        drop(name)

    # --- dataType case sensitivity (explicit schema path) ---
    schema_cases = [
        ("Int64", True),   # legal control
        ("int64", False),  # wrong case
        ("FloatVector", None),
        ("floatvector", False),
        ("varchar", False),
        ("Bogus", False),
        ("", False),
    ]
    for i, (dt, _) in enumerate(schema_cases):
        name = "bnd_dt003_%d" % i
        drop(name)
        schema = {"fields": [
            {"fieldName": "id", "dataType": dt if dt else "", "isPrimary": True},
            {"fieldName": "vec", "dataType": "FloatVector",
             "elementTypeParams": {"dim": 8}},
        ]}
        # need at least one valid vector field; if dt is vector-ish adjust
        if dt in ("FloatVector", "floatvector"):
            schema = {"fields": [
                {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
                {"fieldName": "vec", "dataType": dt, "elementTypeParams": {"dim": 8}},
            ]}
        http, body, raw = safe_request("POST", "v2/vectordb/collections/create",
                                       json={"collectionName": name, "schema": schema})
        print("[dataType=%r] http=%s body=%s" % (dt, http, str(raw)[:200]))
        legal = dt in ("Int64", "FloatVector")
        if http >= 500:
            DEFECTS.append("dataType=%r: Type3 HTTP %s" % (dt, http))
        elif http == 200 and is_ok(body) and not legal:
            DEFECTS.append("dataType=%r: Type1_IllegalSuccess (case-sensitive violation)" % dt)
        drop(name)

if __name__ == "__main__":
    run()
    if DEFECTS:
        for d in DEFECTS:
            print("DEFECT:", d)
        print("VERDICT: DEFECT_FOUND")
    else:
        print("VERDICT: NO_DEFECT")
