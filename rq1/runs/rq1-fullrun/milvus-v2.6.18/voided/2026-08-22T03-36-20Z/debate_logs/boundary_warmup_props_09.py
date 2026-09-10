#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.18
Attack: boundary (warmup property family value domain, create-time)
Constraint: milvus_type_collections_create_007, milvus_state_collections_alter_properties_001
Coverage: (warmup.{vectorIndex}) x {disable, sync, bogus} on create; warmup alter on loaded collection
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _milvus_helper import safe_request, code, drop

BASE = "b_wu_09"

def create_with_params(params, n):
    return safe_request("POST", "collections+create", {
        "collectionName": "%s_%s" % (BASE, n), "dimension": 8, "idType": "Int64",
        "vectorFieldName": "vec", "metricType": "COSINE", "params": params})

def main():
    # valid disable -> code 0
    st, b, raw = create_with_params({"warmup.vectorIndex": "disable"}, "ok")
    print("warmup disable:", raw[:150])
    if code(b) != 0:
        print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — valid warmup disable rejected: %s" % raw[:200]); return
    # valid sync -> code 0
    st, b, raw = create_with_params({"warmup.vectorIndex": "sync"}, "ok2")
    print("warmup sync:", raw[:150])
    if code(b) != 0:
        print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — valid warmup sync rejected: %s" % raw[:200]); return
    # invalid value -> 1100 per contract
    st, b, raw = create_with_params({"warmup.vectorIndex": "bogus"}, "bad")
    print("warmup bogus:", raw[:250])
    if code(b) == 0:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — warmup.vectorIndex='bogus' accepted at create, expected 1100"); return
    if code(b) != 1100:
        print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — warmup bogus rejected with unexpected code %s: %s" % (code(b), raw[:200])); return

    # KNOWN GAP (contract 008): bare 'warmup' key at create -> live v2.6.12 code 0 pass-through
    st, b, raw = create_with_params({"warmup": "bogus"}, "bare")
    print("bare warmup (known gap):", raw[:250])
    if code(b) == 0:
        # confirm not persisted (dropped) vs persisted
        _, bb, _ = safe_request("POST", "collections+describe", {"collectionName": "%s_bare" % BASE})
        props = {p.get("key"): p.get("value") for p in (bb["data"]["properties"])}
        if "warmup" in props:
            print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — bare warmup='bogus' PERSISTED in properties: %r" % props)
            return
        print("OBSERVE: bare warmup accepted+dropped (documented gap, no persistence)")

    # alter warmup on LOADED collection -> ErrCollectionLoaded
    C = "%s_ld" % BASE
    drop(C)
    safe_request("POST", "collections+create", {"collectionName": C, "dimension": 8,
        "idType": "Int64", "vectorFieldName": "vec", "metricType": "COSINE"})
    safe_request("POST", "collections+load", {"collectionName": C})
    st, b, raw = safe_request("POST", "collections+alter_properties", {
        "collectionName": C, "properties": {"warmup.vectorIndex": "sync"}})
    print("alter warmup on loaded:", raw[:250])
    if code(b) == 0:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — warmup alter on loaded collection accepted, expected error"); return

    print("VERDICT: NO_DEFECT — warmup domain + loaded-state guard conform (bare-warmup create gap unpersisted)")

if __name__ == "__main__":
    try:
        main()
    finally:
        for n in ("ok", "ok2", "bad", "bare", "ld"):
            drop("%s_%s" % (BASE, n))
