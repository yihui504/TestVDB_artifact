#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script (R2)
Target: milvus v2.6.16
Attack: empty collections on full-schema create: fields=[], empty-string field names
(fieldName='', dataType=''), empty max_length / dim=0 in elementTypeParams — schema-class
zero/empty matrix. Judged with judge_schema_attack where persistence matters (else expect_rejected).
Constraint: milvus_type_collections_create_002 (fieldName/dataType required),
milvus_range_collections_create_001 (dim bounds), field name rules.
Control: minimal valid schema succeeds (proves schema-mode path healthy).
# exploration_target: novel_candidate
# shape_id: schema_field_empty_zero
# shape_type: numeric_boundary
"""
import os, sys

_sd = os.environ.get("TESTVDB_SCRIPTS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "scripts")
sys.path.insert(0, _sd)
from runtime import get_runtime
rt = get_runtime()

def fields(pk_extra=None, vec_extra=None):
    return {"fields": [
        {"fieldName": "id", "dataType": "Int64", "isPrimary": True,
         **(pk_extra or {})},
        {"fieldName": "vector", "dataType": "FloatVector",
         "elementTypeParams": {"dim": 8}, **(vec_extra or {})},
    ]}

def main():
    # control: minimal valid schema
    s, raw = rt.request("POST", "create_collection",
                        {"collectionName": "bnd_r2_ctrl_28",
                         "schema": fields()})
    print(f"[control schema create] {s} {raw[:150]}")
    if not (s == 200 and '"code":0' in raw.replace(" ", "")):
        print("VERDICT: SCRIPT_ERROR — control failed")
        sys.exit(2)
    rt.drop_collection("bnd_r2_ctrl_28")

    cases = [
        # (label, schema, expect-persistence?)
        ("fields=[]", {"fields": []}, False),
        ("fieldName=''", fields(pk_extra={"fieldName": ""}), False),
        ("dataType=''", fields(pk_extra={"dataType": ""}), False),
        ("dim=0", {"fields": [
            {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
            {"fieldName": "vector", "dataType": "FloatVector",
             "elementTypeParams": {"dim": 0}}]}, False),
        ("dim=-1", {"fields": [
            {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
            {"fieldName": "vector", "dataType": "FloatVector",
             "elementTypeParams": {"dim": -1}}]}, False),
        ("isPrimary='' (string)", fields(pk_extra={"isPrimary": ""}), False),
    ]
    defect = False
    for i, (label, schema, _) in enumerate(cases):
        cname = f"bnd_r2_sch_28_{i}"
        s, raw = rt.request("POST", "create_collection",
                            {"collectionName": cname, "schema": schema})
        v = rt.expect_rejected(s, raw, setup_ok=True)
        print(f"[{label}] {s} {raw[:220]} -> {v}")
        if v == "DEFECT_FOUND":
            defect = True
        rt.drop_collection(cname)

    print("VERDICT: DEFECT_FOUND" if defect else "VERDICT: NO_DEFECT")
    sys.exit(1 if defect else 0)

if __name__ == "__main__":
    main()
