#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script R2
Target: milvus v2.6.17
Attack: insert/upsert non-data body keys: silently swallowed vs effective vs rejected
Constraints: milvus_type_entities_insert_filter_001, B7 surfaces (nprobe/searchParams/filter)
R2 deepens: probe a WIDER family of misplaced keys on insert (limit, offset, consistencyLevel,
outputFields, groupSize, orderBy, exprParams, collectionName dup) and verify whether any
SEMANTICALLY-DANGEROUS one is effective (e.g. limit silently truncating rows).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import (safe_request, code_of, create_collection, load_collection,
                  drop_collection, get_stats)

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

COL = "r2_insbody_002"


def main():
    drop_collection(COL)
    s, b, raw = create_collection(COL)
    print("setup create:", s, raw[:120])
    load_collection(COL)

    base_rows = [{"id": i, "vector": [0.1] * 8, "tags": ["a"]}
                 for i in range(20)]

    # control: plain insert of 20 rows
    s, b, raw = safe_request("POST", "entities+insert",
                             {"collectionName": COL, "data": base_rows})
    n0 = (b or {}).get("data", {}).get("insertCount") if isinstance(b, dict) else None
    print("control insert: code=%s insertCount=%s" % (code_of(b), n0))

    findings = []
    # dangerous misplaced keys: if 'limit' is silently honored on insert path it would truncate
    for key, val in [
        ("limit", 3),
        ("offset", 5),
        ("consistencyLevel", "Strong"),
        ("outputFields", ["id"]),
        ("groupSize", 2),
        ("orderBy", {"order": "ASC", "field": "id"}),
        ("exprParams", {"id": 1}),
        ("filter", "id < 5"),
        ("nprobe", 0),
        ("searchParams", {"nprobe": -5}),
    ]:
        payload = {"collectionName": COL,
                   "data": [{"id": 100 + i, "vector": [0.2] * 8, "tags": ["b"]}
                            for i in range(10)]}
        payload[key] = val
        s, b, raw = safe_request("POST", "entities+insert", payload)
        cd = code_of(b)
        n = None
        if isinstance(b, dict):
            n = (b.get("data") or {}).get("insertCount")
        print("insert extra key %s=%r -> code=%s insertCount=%s" % (key, val, cd, n))
        if cd == 0 and n != 10:
            findings.append("extra key %s=%r AFFECTED insert result (insertCount=%s, expected 10) - silent semantic effect"
                            % (key, val, n))
        if cd not in (0,):
            findings.append("extra key %s=%r rejected code=%s (documented pass-through family says code 0)" % (key, val, cd))

    # verify final count = 20 + 10*10 regardless
    import time
    safe_request("POST", "collections+flush", {"collectionNames": [COL]})
    time.sleep(3)
    cd, rc, raw = get_stats(COL)
    qs, qb, qraw = safe_request("POST", "entities+query",
        {"collectionName": COL, "filter": "id >= 0", "limit": 200, "consistencyLevel": "Strong"})
    qn = len((qb or {}).get("data") or []) if isinstance(qb, dict) else None
    print("final rowCount=%s, strong-query count=%s (expected 120)" % (rc, qn))
    if qn is not None and qn != 120:
        findings.append("strong-query count=%s != 120: some misplaced key altered ingestion" % qn)

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
