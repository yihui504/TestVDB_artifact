#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script (R2)
Target: milvus v2.6.16
Attack: zero/negative values on search-path numeric params: limit=0, limit=-1,
offset=-1, groupSize=0/-1, searchParams.nprobe=0/-1, searchParams.ef=0/-1
(pass-through keys, REST layer unvalidated per contract
milvus_type_entities_insert_002 family / searchParams.ef verified tier).
Constraint: milvus_range_entities_search_001 (1 <= limit+offset), searchParams bounds.
Control: limit=3 valid search succeeds on same collection.
# exploration_target: novel_candidate
# shape_id: search_param_zero_negative
# shape_type: numeric_boundary
"""
import os, sys

_sd = os.environ.get("TESTVDB_SCRIPTS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "scripts")
sys.path.insert(0, _sd)
from runtime import get_runtime
rt = get_runtime()

COLL = "bnd_r2_sr_22"
DIM = 8

def main():
    ok, err = rt.setup_default(COLL, DIM)
    if not ok:
        print(f"VERDICT: SCRIPT_ERROR — setup: {err}")
        sys.exit(2)
    try:
        # control: valid search
        s, raw = rt.request("POST", "search",
                            {"collectionName": COLL, "data": [[0.1] * DIM],
                             "limit": 3})
        print(f"[control limit=3] {s} {raw[:150]}")
        if not (s == 200 and '"code":0' in raw.replace(" ", "")):
            print("VERDICT: SCRIPT_ERROR — control search failed")
            sys.exit(2)

        base = {"collectionName": COLL, "data": [[0.1] * DIM]}
        cases = [
            ("limit=0", {**base, "limit": 0}),
            ("limit=-1", {**base, "limit": -1}),
            ("offset=-1", {**base, "limit": 3, "offset": -1}),
            ("groupSize=0", {**base, "limit": 3, "groupingField": "id",
                             "groupSize": 0}),
            ("nprobe=0", {**base, "searchParams": {"nprobe": 0}}),
            ("nprobe=-1", {**base, "searchParams": {"nprobe": -1}}),
            ("ef=0", {**base, "searchParams": {"ef": 0}}),
            ("ef=-1", {**base, "searchParams": {"ef": -1}}),
        ]
        defect = False
        for label, body in cases:
            s, raw = rt.request("POST", "search", body)
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
