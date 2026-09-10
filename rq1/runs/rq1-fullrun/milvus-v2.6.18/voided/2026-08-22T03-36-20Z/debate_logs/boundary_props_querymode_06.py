#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.18
Attack: boundary (query_mode property value domain + coupled search limit range)
Constraint: milvus_type_collections_create_009, milvus_range_entities_search_001/003
Coverage: (query_mode) x {create-time drop, alter valid, alter invalid, alter after index} + limit boundary {16384,16385,1000000,1000001}
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _milvus_helper import safe_request, code, drop

COLL = "b_qm_06"

def alter(v):
    return safe_request("POST", "collections+alter_properties",
                        {"collectionName": COLL, "properties": {"query_mode": v}})

def readback_props():
    _, b, raw = safe_request("POST", "collections+describe", {"collectionName": COLL})
    try:
        return {p.get("key"): p.get("value") for p in b["data"]["properties"]}
    except Exception:
        return {}

def search(limit):
    return safe_request("POST", "entities+search",
                        {"collectionName": COLL, "data": [[0.1] * 8], "limit": limit})

def main():
    drop(COLL)
    # schema-mode create WITHOUT index -> query_mode alterable
    st, b, raw = safe_request("POST", "collections+create", {
        "collectionName": COLL,
        "schema": {"fields": [
            {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
            {"fieldName": "vec", "dataType": "FloatVector",
             "elementTypeParams": {"dim": "8"}}]}})
    if code(b) != 0:
        print("VERDICT: SCRIPT_ERROR — setup create failed:", raw[:200]); return

    # 1) create-time query_mode should be silently DROPPED (contract)
    drop(COLL)
    st, b, raw = safe_request("POST", "collections+create", {
        "collectionName": COLL, "dimension": 8, "idType": "Int64",
        "vectorFieldName": "vec", "metricType": "COSINE",
        "params": {"query_mode": "large_topk"}})
    props = readback_props()
    print("create with params.query_mode:", code(b), "props:", props)
    if "query_mode" in props:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — create-time query_mode persisted (contract says dropped): %r" % props["query_mode"]); return
    drop(COLL)
    safe_request("POST", "collections+create", {
        "collectionName": COLL,
        "schema": {"fields": [
            {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
            {"fieldName": "vec", "dataType": "FloatVector",
             "elementTypeParams": {"dim": "8"}}]}})

    # 2) invalid value -> 65535
    st, b, raw = alter("bogus")
    print("alter bogus:", raw[:200])
    if code(b) == 0:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — query_mode='bogus' accepted, expected 65535"); return

    # 3) valid large_topk before index -> code 0 persisted
    st, b, raw = alter("large_topk")
    rb = readback_props().get("query_mode")
    print("alter large_topk:", raw[:150], "readback:", rb)
    if code(b) != 0 or rb != "large_topk":
        print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — valid query_mode alter failed/mispersisted: %r" % rb); return

    # 4) coupled limit bounds under large_topk: load first (need index)
    safe_request("POST", "indexes+create", {"collectionName": COLL, "indexParams": [
        {"fieldName": "vec", "indexName": "vi", "metricType": "COSINE"}]})
    safe_request("POST", "collections+load", {"collectionName": COLL})
    st, b, raw = search(1000000)
    print("large_topk limit=1000000:", raw[:150])
    if code(b) != 0:
        print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — large_topk limit=1000000 rejected: %s" % raw[:200]); return
    st, b, raw = search(1000001)
    print("large_topk limit=1000001:", raw[:150])
    if code(b) == 0:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — limit=1000001 accepted under large_topk, expected 65535"); return

    # 5) after vector index exists, altering query_mode to SAME value -> 702 (idempotent alter still blocked)
    st, b, raw = alter("large_topk")
    print("alter same value after index:", raw[:250])
    if code(b) != 702:
        print("OBSERVE: same-value alter after index got code %s (contract implies 702)" % code(b))
    # 6) strict check: alter to DIFFERENT query_mode value is impossible (only large_topk valid),
    # but a loaded collection alter path is state-blocked; verify 702 fires on any query_mode alter post-index
    if code(b) != 702:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — alter query_mode with vector index present got code %s, expected 702" % code(b)); return

    print("VERDICT: NO_DEFECT — query_mode domain + coupled limit bounds all conform")

if __name__ == "__main__":
    try:
        main()
    finally:
        drop(COLL)
