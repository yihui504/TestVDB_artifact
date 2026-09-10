#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.3.22
Attack: load state machine — release -> NotLoad; search on NotLoad must fail;
        loadProgress range 0-100; NotExist -> collection-not-found
Constraints: milvus_state_release_001, milvus_state_search_001,
             milvus_range_get_load_state_001, milvus_behavioral_load_state_001
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
COLL = "bnd_load010"

def get_state(name):
    http, body, raw = safe_request("POST", "v2/vectordb/collections/get_load_state",
                                   json={"collectionName": name})
    st = None
    prog = None
    if is_ok(body):
        st = body.get("data", {}).get("loadState")
        prog = body.get("data", {}).get("loadProgress")
    return http, st, prog, raw

def run():
    try:
        safe_request("POST", "v1/vector/collections/drop", json={"collectionName": COLL})
        # NotExist: get_load_state on missing collection -> collection-not-found error
        http, st, prog, raw = get_state(COLL + "_missing")
        print("[get_load_state missing] http=%s body=%s" % (http, str(raw)[:250]))
        if http == 200 and is_ok(json.loads(raw)) and st in ("NotLoad", "Loading", "Loaded"):
            DEFECTS.append("get_load_state on missing collection returned loadState=%s (no error)" % st)

        # create via v2 quick-create (NOT auto-loaded: quick-create auto-loads? v2 quick-create loads)
        http, body, raw = safe_request("POST", "v2/vectordb/collections/create",
                                       json={"collectionName": COLL, "dimension": 8})
        print("[v2 create] http=%s body=%s" % (http, str(raw)[:150]))
        if not is_ok(body):
            print("VERDICT: SCRIPT_ERROR — create failed")
            return
        # wait for load
        for _ in range(20):
            http, st, prog, raw = get_state(COLL)
            if str(st).endswith("Loaded"):
                break
            time.sleep(1)
        print("[initial state] %s progress=%s" % (st, prog))
        if prog is not None:
            try:
                if not (0 <= int(prog) <= 100) and int(prog) != -1:
                    DEFECTS.append("loadProgress=%s out of [0,100]/-1 range" % prog)
            except Exception:
                DEFECTS.append("loadProgress=%r non-numeric" % prog)

        # release -> NotLoad
        http, body, raw = safe_request("POST", "v2/vectordb/collections/release",
                                       json={"collectionName": COLL})
        print("[release] http=%s body=%s" % (http, str(raw)[:150]))
        time.sleep(2)
        http, st, prog, raw = get_state(COLL)
        print("[after release] state=%s progress=%s" % (st, prog))
        if not str(st).endswith("NotLoad"):
            DEFECTS.append("after release loadState=%s (expected NotLoad)" % st)

        # search on NotLoad collection -> must fail (state machine contract)
        http, body, raw = safe_request("POST", "v2/vectordb/entities/search",
                                       json={"collectionName": COLL,
                                             "data": [[0.1] * 8], "limit": 3})
        print("[search on NotLoad] http=%s body=%s" % (http, str(raw)[:250]))
        if http == 200 and is_ok(body):
            DEFECTS.append("search succeeded on NotLoad collection (Type1)")

        # v1 search on NotLoad too
        http, body, raw = safe_request("POST", "v1/vector/search",
                                       json={"collectionName": COLL, "vector": [0.1] * 8})
        print("[v1 search on NotLoad] http=%s body=%s" % (http, str(raw)[:250]))
        if http == 200 and is_ok(body):
            DEFECTS.append("v1 search succeeded on NotLoad collection (Type1)")

        # reload -> eventually Loaded
        safe_request("POST", "v2/vectordb/collections/load", json={"collectionName": COLL})
        loaded = False
        for _ in range(30):
            http, st, prog, raw = get_state(COLL)
            if str(st).endswith("Loaded"):
                loaded = True
                break
            time.sleep(1)
        print("[after reload] state=%s loaded=%s" % (st, loaded))
        if not loaded:
            DEFECTS.append("collection never reached Loaded after load (timeout)")
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
