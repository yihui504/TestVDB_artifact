#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Vein-mining Script
Target: milvus v2.3.22
Vein: semantic validation gap — filter referencing a NON-EXISTENT field is silently
      accepted with code 200 and empty results (query AND search), instead of a
      field-not-found error. Genuinely invalid exprs (syntax, type mismatch) DO error.
Control group: valid filter returns rows; type-mismatch filter 'id > "abc"' errors 65535
        -> expr engine CAN report errors; nonexistent-field is silently swallowed.
Source: expr plan execution treats unknown column as always-false predicate.
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

COLL = "vein_flt_003"

def run():
    try:
        safe_request("POST", "v2/vectordb/collections/drop", json={"collectionName": COLL})
        _, b, _ = safe_request("POST", "v2/vectordb/collections/create",
            json={"collectionName": COLL, "dimension": 4, "metricType": "L2", "autoId": False})
        if not is_ok(b):
            print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
        safe_request("POST", "v2/vectordb/collections/load", json={"collectionName": COLL})
        for _ in range(20):
            _, bl, _ = safe_request("POST", "v2/vectordb/collections/get_load_state",
                                    json={"collectionName": COLL})
            if is_ok(bl) and bl.get("data", {}).get("loadState") in ("LoadStateLoaded", "Loaded"):
                break
            time.sleep(1)
        _, b, _ = safe_request("POST", "v2/vectordb/entities/insert",
            json={"collectionName": COLL,
                  "data": [{"id": i, "vector": [float(i), 0, 0, 0]} for i in range(1, 6)]})
        if not is_ok(b):
            print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
        time.sleep(3)
        # control 1: valid filter returns rows
        _, qv, _ = safe_request("POST", "v2/vectordb/entities/query",
            json={"collectionName": COLL, "filter": "id > 0", "limit": 5})
        n_valid = len(qv.get("data", [])) if is_ok(qv) else -1
        # control 2: expr engine can error (type mismatch)
        _, qt, _ = safe_request("POST", "v2/vectordb/entities/query",
            json={"collectionName": COLL, "filter": 'id > "abc"', "limit": 5})
        code_typo_type = qt.get("code") if isinstance(qt, dict) else -1
        # target: nonexistent field filter on query
        _, qn, _ = safe_request("POST", "v2/vectordb/entities/query",
            json={"collectionName": COLL, "filter": "nonexistent_field > 0", "limit": 5})
        # target 2: same on search
        _, sn, _ = safe_request("POST", "v2/vectordb/entities/search",
            json={"collectionName": COLL, "data": [[0, 0, 0, 0]], "limit": 5,
                  "filter": "nonexistent_field > 0"})
        c_q = qn.get("code") if isinstance(qn, dict) else -1
        c_s = sn.get("code") if isinstance(sn, dict) else -1
        print(f"valid filter rows={n_valid}; type-mismatch code={code_typo_type}; "
              f"nonexistent-field query code={c_q}, search code={c_s}")
        if n_valid == 5 and code_typo_type != 200 and c_q == 200 and c_s == 200:
            print("Detail: filter on nonexistent field silently accepted (code 200, empty "
                  "data) on both query and search, while other invalid exprs get 65535 — "
                  "user typo yields misleading 'no results' instead of an error")
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
