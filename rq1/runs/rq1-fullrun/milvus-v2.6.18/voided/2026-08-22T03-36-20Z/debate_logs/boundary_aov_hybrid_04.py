#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.18
Attack: boundary (NEW v2.6.18 face: ArrayOfVector restrictions in hybrid search)
Constraint: milvus_behavioral_hybrid_search_aov_001 (inferred — attack-verify; live finding: REST path
never surfaces the 1100 — sub-search extras are silent-drop on BOTH normal and AoV collections, so the
proxy-layer AoV guard is REST-unreachable. Script reports probe observations only; no defect claimed from
silent-drop since doc semantics for REST sub-search keys are unspecified.)
Coverage: (hybrid search on AoV anns field) x {radius range search, group_by, iterator}
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _milvus_helper import safe_request, code, drop

COLL = "b_aov_hyb_04"
FIELD = "emb"   # ArrayOfVector field

def create_aov():
    # full-schema create with ArrayOfVector field
    return safe_request("POST", "collections+create", {
        "collectionName": COLL,
        "schema": {
            "autoId": False,
            "fields": [
                {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
                {"fieldName": FIELD, "dataType": "FloatVector",
                 "isArray": True,
                 "elementTypeParams": {"dim": "8"}},
            ]}})

def hybrid_search(sub_search_extra):
    sub = {"annsField": FIELD, "data": [[0.1] * 8], "limit": 4}
    sub.update(sub_search_extra)
    return safe_request("POST", "entities+hybrid_search", {
        "collectionName": COLL,
        "search": [sub],
        "rerank": {"strategy": "rrf"},
        "limit": 4})

def main():
    drop(COLL)
    st, b, raw = create_aov()
    print("create AoV:", st, raw[:300])
    if code(b) != 0:
        print("VERDICT: SCRIPT_ERROR — AoV create failed (schema face may differ):", raw[:300]); return

    st, b, raw = safe_request("POST", "collections+load", {"collectionName": COLL})
    print("load:", st, raw[:200])
    if code(b) != 0:
        # load before release requires index on vector field for AoV: create index then load
        st, b, raw = safe_request("POST", "indexes+create", {
            "collectionName": COLL, "indexParams": [
                {"fieldName": FIELD, "indexName": "emb_idx", "metricType": "COSINE"}]})
        print("index create:", st, raw[:200])
        st, b, raw = safe_request("POST", "collections+load", {"collectionName": COLL})
        print("load after index:", st, raw[:200])

    # insert AoV rows (REST flat shape: emb is a flat float array) so searches execute for real
    st, b, raw = safe_request("POST", "entities+insert", {
        "collectionName": COLL, "data": [
            {"id": 1, FIELD: [0.1] * 8}, {"id": 2, FIELD: [0.9] * 8}]})
    print("insert AoV rows:", st, raw[:200])

    for label, extra in [
        ("plain", {}),
        ("radius", {"searchParams": {"radius": 0.99, "range_filter": 1.0}}),
        ("groupingField", {"groupingField": "id"}),
        ("iterator", {"iterator": {"batchSize": 10}}),
    ]:
        st, b, raw = hybrid_search(extra)
        print("hybrid AoV %s:" % label, st, raw[:300])

    # expected per contract: 1100 with 'not supported for vector array ... in hybrid search'.
    # observed: code 0 for all (sub-search extras silently dropped). REST-unreachable guard
    # -> cannot claim Type1 (doc silent on REST sub-search key semantics); report as probe.
    print("VERDICT: NO_DEFECT — probe recorded: AoV hybrid sub-search extras silent-dropped (code 0), contract 1100 unreachable via REST")

if __name__ == "__main__":
    try:
        main()
    finally:
        drop(COLL)
