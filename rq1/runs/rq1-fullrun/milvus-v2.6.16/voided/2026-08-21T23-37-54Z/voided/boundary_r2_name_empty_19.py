#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script (R2)
Target: milvus v2.6.16
Attack: empty-string matrix on name-class required params (collectionName / partitionName / aliasName / newCollectionName)
Constraint: milvus_range_collections_create_002 (name rules; empty name violates naming rules)
Control group: valid names (create/describe succeed) so rejections aren't setup artifacts.
# exploration_target: novel_candidate
# shape_id: name_empty_string_matrix
# shape_type: null_handling
"""
import os, sys

_sd = os.environ.get("TESTVDB_SCRIPTS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "scripts")
sys.path.insert(0, _sd)
from runtime import get_runtime
rt = get_runtime()

COLL = "bnd_r2_name_19"

def main():
    # Control: valid collectionName must succeed (proves endpoint healthy)
    s, raw = rt.request("POST", "collections/create",
                        {"collectionName": COLL, "dimension": 8})
    print(f"[control create valid] {s} {raw[:150]}")
    ctrl_ok = (s == 200 and '"code":0' in raw.replace(" ", ""))
    s, raw = rt.request("POST", "collections/describe", {"collectionName": COLL})
    print(f"[control describe valid] {s} {raw[:150]}")
    ctrl_ok = ctrl_ok and (s == 200 and '"code":0' in raw.replace(" ", ""))
    if not ctrl_ok:
        print("VERDICT: SCRIPT_ERROR — control group failed")
        sys.exit(2)

    defect = False
    # Attack matrix: collectionName="" across endpoints (name-class empty string)
    cases = [
        ("collections/create", "create_collection",
         {"collectionName": "", "dimension": 8}),
        ("collections/describe", "describe_collection", {"collectionName": ""}),
        ("collections/drop", "drop_collection", {"collectionName": ""}),
        ("collections/load", "load_collection", {"collectionName": ""}),
        ("collections/release", "release_collection", {"collectionName": ""}),
        ("collections/get_stats", "collections/get_stats", {"collectionName": ""}),
        ("collections/compact", "collections/compact", {"collectionName": ""}),
        ("collections/rename", "collections/rename",
         {"collectionName": COLL, "newCollectionName": ""}),
        ("partitions/create", "partitions/create",
         {"collectionName": COLL, "partitionName": ""}),
        ("aliases/create", "aliases/create",
         {"collectionName": COLL, "aliasName": ""}),
    ]
    for label, key, body in cases:
        s, raw = rt.request("POST", key, body)
        v = rt.expect_rejected(s, raw, setup_ok=True)
        print(f"[{label} name=''] {s} {raw[:200]} -> {v}")
        if v == "DEFECT_FOUND":
            defect = True
    try:
        rt.drop_collection(COLL)
    except Exception:
        pass
    print("VERDICT: DEFECT_FOUND" if defect else "VERDICT: NO_DEFECT")
    sys.exit(1 if defect else 0)

if __name__ == "__main__":
    main()
