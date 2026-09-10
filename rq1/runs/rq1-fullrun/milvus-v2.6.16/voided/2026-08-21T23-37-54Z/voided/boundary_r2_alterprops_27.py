#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script (R2)
Target: milvus v2.6.16
Attack: collections/alter_properties with empty-string and zero-value property values:
properties {query_mode:""}, {ttl.seconds:0}, {ttl.seconds:-1}, {"": "x"} (empty key),
properties {} (empty object on required field), propertyKeys=[""] / [] at drop_properties.
Constraint: milvus_type_collections_create_009 (query_mode value set is {large_topk};
empty string invalid -> reject), ttl seconds must be positive integer.
Control: alter_properties with valid warmup key path works on released collection;
invalid query_mode='bogus' rejected (R1 confirmed) as same-family control.
# exploration_target: novel_candidate
# shape_id: property_value_empty_zero
# shape_type: numeric_boundary
"""
import os, sys

_sd = os.environ.get("TESTVDB_SCRIPTS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "scripts")
sys.path.insert(0, _sd)
from runtime import get_runtime
rt = get_runtime()

COLL = "bnd_r2_prop_27"

def main():
    # schema-mode create (no indexParams) so query_mode alter is not blocked by 702
    s, raw = rt.request("POST", "create_collection", {
        "collectionName": COLL,
        "schema": {"fields": [
            {"fieldName": "id", "dataType": "Int64", "isPrimary": True,
             "autoID": True},
            {"fieldName": "vector", "dataType": "FloatVector",
             "elementTypeParams": {"dim": 8}},
        ]},
    })
    print(f"[create schema-mode] {s} {raw[:200]}")
    ok = s == 200 and '"code":0' in raw.replace(" ", "")
    if not ok:
        print("VERDICT: SCRIPT_ERROR — control create failed")
        sys.exit(2)
    try:
        # same-family control: bogus value rejected (R1 baseline)
        s, raw = rt.request("POST", "collections+alter_properties",
                            {"collectionName": COLL,
                             "properties": {"query_mode": "bogus"}})
        print(f"[control query_mode='bogus'] {s} {raw[:200]}")

        defect = False
        cases = [
            ("query_mode=''", {"query_mode": ""}),
            ("query_mode=null", {"query_mode": None}),
            ("ttl.seconds=0", {"ttl.seconds": 0}),
            ("ttl.seconds=-1", {"ttl.seconds": -1}),
            ("empty key ''", {"": "x"}),
        ]
        for label, props in cases:
            s, raw = rt.request("POST", "collections+alter_properties",
                                {"collectionName": COLL, "properties": props})
            v = rt.expect_rejected(s, raw, setup_ok=True)
            print(f"[alter {label}] {s} {raw[:200]} -> {v}")
            if v == "DEFECT_FOUND":
                defect = True

        for label, keys in [("drop_properties ['']", [""]),
                            ("drop_properties []", [])]:
            s, raw = rt.request("POST", "collections+drop_properties",
                                {"collectionName": COLL, "propertyKeys": keys})
            v = rt.expect_rejected(s, raw, setup_ok=True)
            print(f"[{label}] {s} {raw[:200]} -> {v}")
            if v == "DEFECT_FOUND":
                defect = True

        # properties={} empty object (required param present but empty)
        s, raw = rt.request("POST", "collections+alter_properties",
                            {"collectionName": COLL, "properties": {}})
        print(f"[alter properties={{}}] {s} {raw[:200]} -> recorded")

        print("VERDICT: DEFECT_FOUND" if defect else "VERDICT: NO_DEFECT")
        sys.exit(1 if defect else 0)
    finally:
        rt.drop_collection(COLL)

if __name__ == "__main__":
    main()
