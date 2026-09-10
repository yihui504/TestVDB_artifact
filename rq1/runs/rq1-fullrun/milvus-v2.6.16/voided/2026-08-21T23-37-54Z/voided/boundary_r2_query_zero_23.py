#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script (R2)
Target: milvus v2.6.16
Attack: zero/negative on entities/query (limit=0, limit=-1, offset=-1) and
entities/get outputFields=[] empty array + consistencyLevel='' empty enum.
Constraint: milvus_type_entities_search_001 (consistencyLevel enum — empty string
not in enum), limit/offset window rules (query shares the [1,16384] window).
Control: valid query limit=3 succeeds.
# exploration_target: novel_candidate
# shape_id: query_param_zero_negative
# shape_type: numeric_boundary
"""
import os, sys

_sd = os.environ.get("TESTVDB_SCRIPTS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "scripts")
sys.path.insert(0, _sd)
from runtime import get_runtime
rt = get_runtime()

COLL = "bnd_r2_q_23"
DIM = 8

def main():
    ok, err = rt.setup_default(COLL, DIM)
    if not ok:
        print(f"VERDICT: SCRIPT_ERROR — setup: {err}")
        sys.exit(2)
    try:
        s, raw = rt.request("POST", "query",
                            {"collectionName": COLL, "filter": "id >= 0",
                             "limit": 3})
        print(f"[control query] {s} {raw[:150]}")
        if not (s == 200 and '"code":0' in raw.replace(" ", "")):
            print("VERDICT: SCRIPT_ERROR — control query failed")
            sys.exit(2)

        cases = [
            ("query limit=0", "query",
             {"collectionName": COLL, "filter": "id >= 0", "limit": 0}),
            ("query limit=-1", "query",
             {"collectionName": COLL, "filter": "id >= 0", "limit": -1}),
            ("query offset=-1", "query",
             {"collectionName": COLL, "filter": "id >= 0", "limit": 3,
              "offset": -1}),
            ("query consistencyLevel=''", "query",
             {"collectionName": COLL, "filter": "id >= 0", "limit": 3,
              "consistencyLevel": ""}),
            ("search consistencyLevel=''", "search",
             {"collectionName": COLL, "data": [[0.1] * DIM], "limit": 3,
              "consistencyLevel": ""}),
            ("get outputFields=[]", "get_points",
             {"collectionName": COLL, "id": [0], "outputFields": []}),
        ]
        defect = False
        for label, key, body in cases:
            s, raw = rt.request("POST", key, body)
            v = rt.expect_rejected(s, raw, setup_ok=True)
            print(f"[{label}] {s} {raw[:200]} -> {v}")
            if v == "DEFECT_FOUND":
                defect = True
        print("VERDICT: DEFECT_FOUND" if defect else "VERDICT: NO_DEFECT")
        sys.exit(1 if defect else 0)
    finally:
        rt.drop_collection(COLL)

if __name__ == "__main__":
    main()
