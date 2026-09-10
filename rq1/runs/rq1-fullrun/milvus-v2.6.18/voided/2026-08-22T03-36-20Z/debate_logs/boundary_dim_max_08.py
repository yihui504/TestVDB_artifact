#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.18
Attack: boundary (vector dimension max)
Constraint: milvus_range_collections_create_001
Coverage: (dimension) x {32768 max, 32769 over, 1 below}
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _milvus_helper import safe_request, code, drop

BASE = "b_dim_08"

def create(dim):
    return safe_request("POST", "collections+create", {
        "collectionName": "%s_%d" % (BASE, dim), "dimension": dim,
        "idType": "Int64", "vectorFieldName": "vec", "metricType": "COSINE"})

def main():
    made = []
    # max boundary: 32768 should succeed
    st, b, raw = create(32768)
    made.append("%s_32768" % BASE)
    print("dim=32768:", st, raw[:150])
    if code(b) != 0:
        print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — dim=32768 (documented max) rejected: %s" % raw[:200]); return

    # over max
    st, b, raw = create(32769)
    print("dim=32769:", st, raw[:200])
    if code(b) == 0:
        made.append("%s_32769" % BASE)
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — dim=32769 accepted, expected reject (max 32768)"); return

    # below min
    st, b, raw = create(1)
    print("dim=1:", st, raw[:200])
    if code(b) == 0:
        made.append("%s_1" % BASE)
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — dim=1 accepted, expected reject (min 2)"); return

    print("VERDICT: NO_DEFECT — dimension bounds [2,32768] enforced")

if __name__ == "__main__":
    try:
        main()
    finally:
        for n in ("b_dim_08_32768", "b_dim_08_32769", "b_dim_08_1"):
            drop(n)
