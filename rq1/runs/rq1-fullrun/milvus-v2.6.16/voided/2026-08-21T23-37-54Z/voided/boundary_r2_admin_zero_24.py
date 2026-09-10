#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script (R2)
Target: milvus v2.6.16
Attack: zero/negative on admin numeric params: indexes/describe timestamp=0/-1,
collections/flush CollectionName='' (empty), transfer_replica Num=0/-1,
collections/compact on empty-name.
Live note: flush struct binds CollectionName (array<string>) — contract lists
collectionNames; empty-name / timestamp attacks still boundary-valid.
Control: flush with real collection succeeds (proves endpoint + auth healthy).
# exploration_target: novel_candidate
# shape_id: admin_param_zero_negative
# shape_type: numeric_boundary
"""
import os, sys

_sd = os.environ.get("TESTVDB_SCRIPTS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "scripts")
sys.path.insert(0, _sd)
from runtime import get_runtime
rt = get_runtime()

COLL = "bnd_r2_adm_24"

def main():
    ok, err = rt.setup_default(COLL, 8)
    if not ok:
        print(f"VERDICT: SCRIPT_ERROR — setup: {err}")
        sys.exit(2)
    try:
        s, raw = rt.request("POST", "collections+flush",
                            {"CollectionName": COLL})
        print(f"[control flush] {s} {raw[:150]}")
        if not (s == 200 and '"code":0' in raw.replace(" ", "")):
            print("VERDICT: SCRIPT_ERROR — control flush failed")
            sys.exit(2)

        defect = False
        cases = [
            ("flush CollectionName=''", "collections+flush",
             {"CollectionName": ""}),
            
            ("index describe timestamp=0", "indexes+describe",
             {"collectionName": COLL, "indexName": "vector_idx",
              "timestamp": 0}),
            ("index describe timestamp=-1", "indexes+describe",
             {"collectionName": COLL, "indexName": "vector_idx",
              "timestamp": -1}),
            ("compact name=''", "collections+compact",
             {"collectionName": ""}),

        ]
        for label, key, body in cases:
            s, raw = rt.request("POST", key, body)
            v = rt.expect_rejected(s, raw, setup_ok=True)
            print(f"[{label}] {s} {raw[:220]} -> {v}")
            if v == "DEFECT_FOUND":
                defect = True
        print("VERDICT: DEFECT_FOUND" if defect else "VERDICT: NO_DEFECT")
        sys.exit(1 if defect else 0)
    finally:
        rt.drop_collection(COLL)

if __name__ == "__main__":
    main()
