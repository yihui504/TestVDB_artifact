#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.3.22
Attack: collection name boundary values — empty/unicode/SQL chars/NUL/very long
Constraint: collectionName (string, required) on v1/v2 create + describe behavioral contract
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

def drop(name, api="v1"):
    p = "v1/vector/collections/drop" if api == "v1" else "v2/vectordb/collections/drop"
    try:
        safe_request("POST", p, json={"collectionName": name})
    except Exception:
        pass

def run():
    names = [
        ("empty", ""),
        ("space", " "),
        ("nul", "a\x00b"),
        ("unicode", "coll中文🎯"),
        ("sql", "c'; DROP TABLE--"),
        ("dots", "a.b.c"),
        ("dollar", "$gt"),
        ("300chars", "L" * 300),
    ]
    for tag, nm in names:
        for api, path in (("v1", "v1/vector/collections/create"),
                          ("v2", "v2/vectordb/collections/create")):
            body_json = {"collectionName": nm, "dimension": 8}
            http, body, raw = safe_request("POST", path, json=body_json)
            print("[%s %s name=%r...] http=%s body=%s"
                  % (api, tag, nm[:20], http, str(raw)[:200]))
            if http >= 500:
                DEFECTS.append("%s name %s: Type3 HTTP %s" % (api, tag, http))
            elif http == 200 and is_ok(body):
                # accepted: read back and confirm persistence fidelity
                dpath = ("v1/vector/collections/describe" if api == "v1"
                         else "v2/vectordb/collections/describe")
                if api == "v1":
                    h2, b2, r2 = safe_request("GET", dpath, params={"collectionName": nm})
                else:
                    h2, b2, r2 = safe_request("POST", dpath, json={"collectionName": nm})
                print("  [readback] http=%s body=%s" % (h2, str(r2)[:200]))
                if h2 == 200 and not is_ok(b2):
                    DEFECTS.append("%s name %s: created but describe cannot find (state mismatch)" % (api, tag))
                elif tag in ("nul",) and is_ok(b2):
                    DEFECTS.append("%s accepted NUL byte in name (silent accept)" % api)
            drop(nm, api)

if __name__ == "__main__":
    run()
    if DEFECTS:
        for d in DEFECTS:
            print("DEFECT:", d)
        print("VERDICT: DEFECT_FOUND")
    else:
        print("VERDICT: NO_DEFECT")
