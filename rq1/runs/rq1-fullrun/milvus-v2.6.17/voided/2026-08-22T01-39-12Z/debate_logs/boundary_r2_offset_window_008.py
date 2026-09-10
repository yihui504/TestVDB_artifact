#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script R2
Target: milvus v2.6.17
Attack: search offset + limit window coupling on NORMAL collection (16384) and
        offset alone edge shapes (offset huge, offset 16384 w/ limit 1, offset -1, offset 0)
Constraint: milvus_range_entities_search_001 (limit+offset <= 16384), _002 (default 100)
R1 tested limit values; offset window shapes untested.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import (safe_request, code_of, create_collection, load_collection,
                  drop_collection)

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

COL = "r2off_008"


def search(limit=None, offset=None, note=""):
    p = {"collectionName": COL, "data": [[0.1] * 8]}
    if limit is not None:
        p["limit"] = limit
    if offset is not None:
        p["offset"] = offset
    s, b, raw = safe_request("POST", "entities+search", p)
    cd = code_of(b)
    n = None
    if isinstance(b, dict):
        d = b.get("data")
        if isinstance(d, list):
            n = len(d)
    print("%-44s -> code=%-5s n=%-4s %s" % (note, cd, n, raw[:120]))
    return cd


def main():
    drop_collection(COL)
    s, b, raw = create_collection(COL)
    print("setup:", code_of(b))
    load_collection(COL)
    safe_request("POST", "entities+insert", {
        "collectionName": COL,
        "data": [{"id": i, "vector": [0.1 + i * 0.001] * 8, "tags": ["t"]}
                 for i in range(50)]})

    findings = []
    # window boundary on normal mode: limit+offset
    cd = search(16383, 1, "limit 16383 + offset 1 = 16384 (at max)")
    if cd != 0:
        findings.append("limit+offset=16384 rejected (at max should pass)")
    cd = search(16384, 1, "limit 16384 + offset 1 = 16385 (max+1)")
    if cd == 0:
        findings.append("limit+offset=16385 accepted (window max 16384 bypass)")
    # offset alone huge with tiny limit (window ok by sum? 1+1000000 > 16384)
    cd = search(1, 1000000, "limit 1 + offset 1000000")
    if cd == 0:
        findings.append("offset 1000000 with limit 1 accepted (window > 16384)")
    # offset -1 / limit -1 shapes
    cd = search(-1, None, "limit -1")
    if cd == 0:
        findings.append("search limit=-1 accepted (range [1,16384])")
    cd = search(10, -1, "offset -1")
    if cd == 0:
        findings.append("offset=-1 accepted")
    # offset 0 vs missing equivalence + default limit check
    cd = search(None, None, "no limit/offset (default 100 expected, only 50 rows)")
    cd = search(None, 0, "offset 0 only")

    try:
        drop_collection(COL)
    except Exception:
        pass

    if findings:
        for f in findings:
            print("FINDING: " + f)
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)")
    else:
        print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
