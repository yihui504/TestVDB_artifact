#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.3.22
Attack: index creation boundary — illegal index_type, negative M/efConstruction/nlist,
        huge nlist; read back via indexes/describe
Constraint: v2/vectordb/indexes/create indexParams shape
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
COLL = "bnd_idx014"

def drop(name):
    try:
        safe_request("POST", "v2/vectordb/collections/drop", json={"collectionName": name})
    except Exception:
        pass

def run():
    try:
        # explicit schema WITHOUT indexParams so we can create index separately
        drop(COLL)
        schema = {"fields": [
            {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
            {"fieldName": "vector", "dataType": "FloatVector",
             "elementTypeParams": {"dim": 8}},
        ]}
        http, body, raw = safe_request("POST", "v2/vectordb/collections/create",
                                       json={"collectionName": COLL, "schema": schema})
        print("[create] http=%s body=%s" % (http, str(raw)[:150]))
        if not is_ok(body):
            print("VERDICT: SCRIPT_ERROR — create failed: %s" % str(raw)[:150])
            return

        cases = [
            ("bogus index_type", {"index_type": "NOT_AN_INDEX"}),
            ("empty index_type", {"index_type": ""}),
            ("M=0", {"index_type": "HNSW", "M": 0}),
            ("M=-1", {"index_type": "HNSW", "M": -1}),
            ("efConstruction=-5", {"index_type": "HNSW", "efConstruction": -5}),
            ("nlist=0", {"index_type": "IVF_FLAT", "nlist": 0}),
            ("nlist=-1", {"index_type": "IVF_FLAT", "nlist": -1}),
            ("nlist=1e9", {"index_type": "IVF_FLAT", "nlist": 1000000000}),
            ("M as string", {"index_type": "HNSW", "M": "16"}),
        ]
        for tag, params in cases:
            # drop existing index first (best effort)
            safe_request("POST", "v2/vectordb/indexes/drop",
                        json={"collectionName": COLL, "indexName": "vector_idx"})
            time.sleep(1)
            ip = [{"fieldName": "vector", "indexName": "vector_idx",
                   "metricType": "L2", "params": params}]
            http, body, raw = safe_request("POST", "v2/vectordb/indexes/create",
                                           json={"collectionName": COLL, "indexParams": ip})
            print("[%s] http=%s body=%s" % (tag, http, str(raw)[:220]))
            if http >= 500:
                DEFECTS.append("%s: Type3 HTTP %s" % (tag, http))
            elif http == 200 and is_ok(body):
                # accepted; illegal semantics? read back persisted params
                h2, b2, r2 = safe_request("POST", "v2/vectordb/indexes/describe",
                                          json={"collectionName": COLL, "indexName": "vector_idx"})
                print("  [readback] %s" % str(r2)[:250])
                if tag in ("M=0", "M=-1", "efConstruction=-5", "nlist=0", "nlist=-1"):
                    DEFECTS.append("%s: Type1_IllegalSuccess (accepted illegal value)" % tag)

        # control: valid index
        safe_request("POST", "v2/vectordb/indexes/drop",
                    json={"collectionName": COLL, "indexName": "vector_idx"})
        time.sleep(1)
        http, body, raw = safe_request("POST", "v2/vectordb/indexes/create",
                                       json={"collectionName": COLL,
                                             "indexParams": [{"fieldName": "vector",
                                                              "indexName": "vector_idx",
                                                              "metricType": "L2",
                                                              "params": {"index_type": "HNSW",
                                                                         "M": 16,
                                                                         "efConstruction": 200}}]})
        print("[valid control] http=%s body=%s" % (http, str(raw)[:200]))
        if not is_ok(body):
            DEFECTS.append("valid index control failed: %s" % str(raw)[:120])
    finally:
        drop(COLL)

if __name__ == "__main__":
    run()
    if DEFECTS:
        for d in DEFECTS:
            print("DEFECT:", d)
        print("VERDICT: DEFECT_FOUND")
    else:
        print("VERDICT: NO_DEFECT")
