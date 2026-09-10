#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script (R2)
Target: milvus v2.6.16
Attack: HNSW index params zero/negative at indexes/create (M=0, M=-1, efConstruction=0,
efConstruction=-1) — schema-class index boundary values.
Constraint: HNSW param bounds (M in [4,64], efConstruction >= 1) must be enforced;
0/-1 must be rejected.
Control: M=16/efConstruction=256 succeeds on a schema-mode collection (no auto-index).
R1 note: quick-create auto-builds a vector index -> "multiple indexes" 702-family
error is a setup artifact; use explicit schema create to keep index slot free.
# exploration_target: novel_candidate
# shape_id: index_param_zero_negative
# shape_type: numeric_boundary
"""
import os, sys

_sd = os.environ.get("TESTVDB_SCRIPTS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "scripts")
sys.path.insert(0, _sd)
from runtime import get_runtime
rt = get_runtime()

COLL = "bnd_r2_idx_21"

SCHEMA = {"fields": [
    {"fieldName": "id", "dataType": "Int64", "isPrimary": True, "autoID": True},
    {"fieldName": "vector", "dataType": "FloatVector",
     "elementTypeParams": {"dim": 8}},
]}

def idx(m, efc):
    return {"collectionName": COLL, "indexParams": [{
        "fieldName": "vector", "indexName": "vector_idx", "indexType": "HNSW",
        "metricType": "L2", "params": {"M": m, "efConstruction": efc}}]}

def drop_idx():
    try:
        rt.request("POST", "indexes+drop",
                   {"collectionName": COLL, "indexName": "vector_idx"})
    except Exception:
        pass

def main():
    try:
        rt.drop_collection(COLL)
    except Exception:
        pass
    s, raw = rt.request("POST", "create_collection",
                        {"collectionName": COLL, "schema": SCHEMA})
    print(f"[create schema-mode coll] {s} {raw[:150]}")
    if not (s == 200 and '"code":0' in raw.replace(" ", "")):
        print("VERDICT: SCRIPT_ERROR — control create failed")
        sys.exit(2)
    try:
        s, raw = rt.request("POST", "create_index", idx(16, 256))
        print(f"[control M=16 efC=256] {s} {raw[:150]}")
        if not (s == 200 and '"code":0' in raw.replace(" ", "")):
            print("VERDICT: SCRIPT_ERROR — control index create failed")
            sys.exit(2)

        defect = False
        for label, params in [("M=0", idx(0, 256)), ("M=-1", idx(-1, 256)),
                              ("efC=0", idx(16, 0)), ("efC=-1", idx(16, -1))]:
            drop_idx()  # one index per field: drop before each attack
            s, raw = rt.request("POST", "create_index", params)
            v = rt.expect_rejected(s, raw, setup_ok=True)
            print(f"[{label}] {s} {raw[:220]} -> {v}")
            if v == "DEFECT_FOUND":
                defect = True
        print("VERDICT: DEFECT_FOUND" if defect else "VERDICT: NO_DEFECT")
        sys.exit(1 if defect else 0)
    finally:
        try: rt.drop_collection(COLL)
        except Exception: pass

if __name__ == "__main__":
    main()
