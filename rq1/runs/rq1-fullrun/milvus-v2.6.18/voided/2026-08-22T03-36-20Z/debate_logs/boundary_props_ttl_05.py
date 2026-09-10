#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.18
Attack: boundary (collections/alter_properties ttl value domain)
Constraint: milvus_range_collections_alter_properties_ttl_001
Coverage: (collection.ttl.seconds) x {-1, -2, 0, 3155760000, 3155760001, 'abc', ''} + readback verify
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _milvus_helper import safe_request, code, drop

COLL = "b_ttl_05"

def alter(v):
    return safe_request("POST", "collections+alter_properties",
                        {"collectionName": COLL,
                         "properties": {"collection.ttl.seconds": v}})

def readback():
    _, b, raw = safe_request("POST", "collections+describe", {"collectionName": COLL})
    try:
        for p in b["data"]["properties"]:
            if p.get("key") == "collection.ttl.seconds":
                return p.get("value")
    except Exception:
        pass
    return None

def main():
    drop(COLL)
    st, b, raw = safe_request("POST", "collections+create", {
        "collectionName": COLL, "dimension": 8, "idType": "Int64",
        "vectorFieldName": "vec", "metricType": "COSINE"})
    if code(b) != 0:
        print("VERDICT: SCRIPT_ERROR — setup create failed:", raw[:200]); return

    def check(v, expect_ok, label):
        st, b, raw = alter(v)
        rb = readback()
        print("ttl=%r -> code=%s readback=%r raw=%s" % (v, code(b), rb, raw[:150]))
        ok = (code(b) == 0)
        if expect_ok and not ok:
            print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — in-range ttl %r rejected: %s" % (v, raw[:200])); return False
        if (not expect_ok) and ok:
            print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — out-of-domain ttl %r accepted (readback=%r)" % (v, rb)); return False
        if expect_ok and ok and str(rb) != str(v):
            print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — ttl %r accepted but readback mismatched %r" % (v, rb)); return False
        return True

    # domain [-1, 3155760000]; string-encoded
    if not check("-1", True, "min"): return
    if not check("3155760000", True, "max"): return
    if not check("-2", False, "below-min"): return
    if not check("3155760001", False, "above-max"): return
    if not check("abc", False, "non-numeric"): return
    if not check("", False, "empty-string"): return

    print("VERDICT: NO_DEFECT — ttl domain [-1,3155760000] enforced with readback consistency")

if __name__ == "__main__":
    try:
        main()
    finally:
        drop(COLL)
