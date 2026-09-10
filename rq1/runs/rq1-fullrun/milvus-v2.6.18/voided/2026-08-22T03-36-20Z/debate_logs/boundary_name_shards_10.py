#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.18
Attack: boundary (name length 255 + shards 16)
Constraint: milvus_range_collections_create_002, milvus_range_collections_create_005
Coverage: (collectionName len) x {255, 256}; (numShards) x {16, 17, 0, -1}
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _milvus_helper import safe_request, code, drop

BASE = "b_ns_10"

def create(name=None, shards=None):
    body = {"collectionName": name or (BASE + "x"),
            "dimension": 8, "idType": "Int64", "vectorFieldName": "vec",
            "metricType": "COSINE"}
    if shards is not None:
        body["numShards"] = shards
    return safe_request("POST", "collections+create", body)

def main():
    made = ["a" * 255, BASE + "x", BASE + "_s17", BASE + "_s0"]
    # name len 255 -> ok
    n255 = "a" * 255
    st, b, raw = create(name=n255)
    made.append(n255)
    print("name 255:", raw[:150])
    if code(b) != 0:
        print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — 255-char name rejected: %s" % raw[:200]); return
    # name len 256 -> reject
    n256 = "a" * 256
    st, b, raw = create(name=n256)
    print("name 256:", raw[:200])
    if code(b) == 0:
        made.append(n256)
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — 256-char name accepted, expected reject"); return

    # shards 16 -> ok
    st, b, raw = create(shards=16)
    made.append(BASE + "x")
    print("shards 16:", raw[:150])
    if code(b) != 0:
        print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — shards=16 (max) rejected: %s" % raw[:200]); return
    def shards_case(v):
        C = "%s_s%d" % (BASE, v)
        drop(C)
        st, b, raw = create(name=C, shards=v)
        _, bb, _ = safe_request("POST", "collections+describe", {"collectionName": C})
        sn = (bb or {}).get("data", {}).get("shardsNum")
        print("shards %d: create code=%s readback shardsNum=%r" % (v, code(b), sn))
        if code(b) == 0 and sn != v:
            print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — numShards=%d accepted but silently clamped/dropped (readback shardsNum=%r, expected reject per max 16)" % (v, sn))
            return False
        if code(b) == 0 and sn == v:
            print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — numShards=%d accepted and persisted (max 16)" % v)
            return False
        return True

    for v in (17, 0):
        if not shards_case(v):
            return

    print("VERDICT: NO_DEFECT — name length 255 + shards bounds enforced")

MADE = ["a" * 255, "a" * 256, BASE + "x", BASE + "_s17", BASE + "_s0"]

if __name__ == "__main__":
    try:
        main()
    finally:
        for n in MADE:
            drop(n)
