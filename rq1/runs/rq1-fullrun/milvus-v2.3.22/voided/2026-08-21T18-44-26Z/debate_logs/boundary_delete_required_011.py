#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.3.22
Attack: v1 delete requires exactly one of id/filter; invalid filter -> 1804; get with
        mismatched id type; malformed filter expressions
Constraints: milvus_behavioral_delete_001, milvus_behavioral_query_001, milvus_behavioral_get_001
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
COLL = "bnd_del011"

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
        safe_request("POST", "v1/vector/collections/drop", json={"collectionName": COLL})
        http, body, raw = safe_request("POST", "v1/vector/collections/create",
                                       json={"collectionName": COLL, "dimension": 8})
        if not is_ok(body):
            print("VERDICT: SCRIPT_ERROR — create failed: %s" % str(raw)[:150])
            return
        wait_loaded(COLL)

        # delete with neither id nor filter -> 1802
        http, body, raw = safe_request("POST", "v1/vector/delete",
                                       json={"collectionName": COLL})
        print("[delete no id/filter] http=%s body=%s" % (http, str(raw)[:250]))
        if http >= 500:
            DEFECTS.append("delete no id/filter: Type3 HTTP %s" % http)
        elif http == 200 and is_ok(body):
            DEFECTS.append("delete with neither id nor filter: Type1_IllegalSuccess")

        # delete with BOTH id and filter -> should reject (exactly one)
        http, body, raw = safe_request("POST", "v1/vector/delete",
                                       json={"collectionName": COLL, "id": 1, "filter": "id > 0"})
        print("[delete both id+filter] http=%s body=%s" % (http, str(raw)[:250]))
        if http >= 500:
            DEFECTS.append("delete both: Type3 HTTP %s" % http)

        # invalid filter expressions -> 1804 family
        bad_filters = ["id >>>", "'; DROP TABLE--", "", "id in [notalist]", "vector like '%x%'"]
        for f in bad_filters:
            http, body, raw = safe_request("POST", "v1/vector/query",
                                           json={"collectionName": COLL, "filter": f, "limit": 3})
            print("[query filter=%r] http=%s body=%s" % (f, http, str(raw)[:200]))
            if http >= 500:
                DEFECTS.append("query filter=%r: Type3 HTTP %s" % (f, http))
            elif http == 200 and is_ok(body):
                DEFECTS.append("query filter=%r: Type1_IllegalSuccess" % f)

        # get with wrong id type (string on Int64 PK)
        http, body, raw = safe_request("POST", "v1/vector/get",
                                       json={"collectionName": COLL, "id": "not-a-number"})
        print("[get id='not-a-number'] http=%s body=%s" % (http, str(raw)[:250]))
        if http >= 500:
            DEFECTS.append("get string id on Int64 PK: Type3 HTTP %s" % http)

        # get non-existent id -> code 200 empty array (behavioral control)
        http, body, raw = safe_request("POST", "v1/vector/get",
                                       json={"collectionName": COLL, "id": 99999})
        print("[get id=99999 control] http=%s body=%s" % (http, str(raw)[:200]))
        if is_ok(body):
            d = body.get("data")
            if d is None:
                DEFECTS.append("get non-existent: data null (should be empty array)")
    finally:
        try:
            safe_request("POST", "v1/vector/collections/drop", json={"collectionName": COLL})
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
