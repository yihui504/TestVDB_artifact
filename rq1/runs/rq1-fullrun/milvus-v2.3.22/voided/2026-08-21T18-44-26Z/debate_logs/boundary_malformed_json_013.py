#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.3.22
Attack: malformed JSON / raw body attacks (strategy 7) — NUL bytes, truncated JSON,
        lone surrogate, huge string. Uses data= raw bytes to bypass client serialization.
"""
import requests, json, sys, os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = os.environ.get("TESTVDB_DB_URL", "http://localhost:19530").rstrip("/")
AUTH = os.environ.get("TESTVDB_AUTH_HEADER", "Bearer root:Milvus")

def raw_request(path, raw_bytes):
    url = BASE_URL + "/" + path.lstrip("/")
    headers = {"Content-Type": "application/json"}
    if AUTH:
        headers["Authorization"] = AUTH
    try:
        r = requests.post(url, data=raw_bytes, headers=headers, timeout=60)
    except Exception as e:
        return 0, repr(e)
    return r.status_code, r.text

DEFECTS = []

def run():
    cases = [
        ("truncated json", b'{"collectionName": "x", "dimension": '),
        ("trailing comma", b'{"collectionName": "x", "dimension": 8,}'),
        ("single quotes", b"{'collectionName': 'x', 'dimension': 8}"),
        ("comment injection", b'{"collectionName": "x" // c, "dimension": 8}'),
        ("bad escape", b'{"collectionName": "\\q", "dimension": 8}'),
        ("lone surrogate", b'{"collectionName": "\\ud800bad", "dimension": 8}'),
        ("nul in value", b'{"collectionName": "a\\u0000b", "dimension": 8}'),
        ("extra brace", b'{"collectionName": "x", "dimension": 8}}'),
        ("array body", b'[{"collectionName": "x", "dimension": 8}]'),
        ("string body", b'"just a string"'),
        ("empty body", b''),
        ("huge value", b'{"collectionName": "' + b'A' * 1000000 + b'", "dimension": 8}'),
    ]
    targets = ["v1/vector/collections/create", "v2/vectordb/collections/create",
               "v1/vector/search", "v2/vectordb/entities/search"]
    for t in targets:
        for tag, body in cases:
            http, txt = raw_request(t, body)
            print("[%s | %s] http=%s body=%s" % (t.split("/")[-1], tag, http, txt[:160]))
            if http >= 500:
                DEFECTS.append("%s %s: Type3_RuntimeFailure HTTP %s" % (t, tag, http))
            elif "panic" in txt.lower() or "runtime error" in txt.lower():
                DEFECTS.append("%s %s: panic leaked in response" % (t, tag))

if __name__ == "__main__":
    run()
    if DEFECTS:
        for d in DEFECTS:
            print("DEFECT:", d)
        print("VERDICT: DEFECT_FOUND")
    else:
        print("VERDICT: NO_DEFECT")
