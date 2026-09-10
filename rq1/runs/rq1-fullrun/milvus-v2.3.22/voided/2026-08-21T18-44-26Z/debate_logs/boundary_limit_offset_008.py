#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.3.22
Attack: limit/offset boundary values (v1 search + v1/v2 query)
Constraint: milvus_range_v1_search_defaults_001 (limit default 100, offset 0)
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
COLL = "bnd_lim008"

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
        safe_request("POST", "v1/vector/insert",
                    json={"collectionName": COLL,
                          "data": [{"vector": [0.1] * 8}, {"vector": [0.2] * 8}]})

        cases = [
            ("limit=0", {"limit": 0}, "reject"),
            ("limit=-1", {"limit": -1}, "reject"),
            ("limit='3'(str)", {"limit": "3"}, "reject"),
            ("limit=null", {"limit": None}, "reject"),
            ("limit=1.5", {"limit": 1.5}, "reject"),
            ("offset=-5", {"offset": -5}, "reject"),
            ("limit=INT32_MAX", {"limit": 2147483647}, "either"),
            ("limit=16385 (>max topK)", {"limit": 16385}, "either"),
        ]
        for case, extra, expect in cases:
            payload = {"collectionName": COLL, "vector": [0.1] * 8}
            payload.update(extra)
            http, body, raw = safe_request("POST", "v1/vector/search", json=payload)
            print("[%s] http=%s body=%s" % (case, http, str(raw)[:220]))
            if http >= 500:
                DEFECTS.append("%s: Type3 HTTP %s" % (case, http))
            elif expect == "reject" and http == 200 and is_ok(body):
                DEFECTS.append("%s: Type1_IllegalSuccess" % case)
            elif expect == "either" and http == 200 and is_ok(body):
                n = len(body.get("data") or [])
                if extra.get("limit") is not None and extra["limit"] <= 2 and n > extra["limit"]:
                    DEFECTS.append("%s: returned %d > limit" % (case, n))

        # control: default limit (100) with 2 rows inserted; retry for Bounded consistency
        n = -1
        for _ in range(6):
            http, body, raw = safe_request("POST", "v1/vector/search",
                                           json={"collectionName": COLL, "vector": [0.1] * 8})
            n = len((body or {}).get("data") or [])
            if n == 2:
                break
            time.sleep(2)
        print("[default limit control] http=%s n=%s" % (http, n))
        if n == 0:
            DEFECTS.append("default limit=100: 0 rows returned after retries (visibility)")
        elif n > 100:
            DEFECTS.append("default limit=100: returned %d > 100 rows" % n)

        # v2 query limit boundary
        for case, lim in (("v2 query limit=0", 0), ("v2 query limit=-1", -1)):
            http, body, raw = safe_request("POST", "v2/vectordb/entities/query",
                                           json={"collectionName": COLL,
                                                 "filter": "id >= 0", "limit": lim})
            print("[%s] http=%s body=%s" % (case, http, str(raw)[:200]))
            if http >= 500:
                DEFECTS.append("%s: Type3 HTTP %s" % (case, http))
            elif http == 200 and is_ok(body) and lim <= 0:
                n = len(body.get("data") or [])
                if n > 0:
                    DEFECTS.append("%s: Type1_IllegalSuccess returned %d rows" % (case, n))
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
