#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script R2
Target: milvus v2.6.17
Attack: max fields per collection (64) and max vector fields (4) boundary
Constraint: milvus_range_collections_create_003
Probe: 63/64/65 scalar fields; 4/5 vector fields; duplicate field names in schema
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import safe_request, code_of, drop_collection

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def mkcol(name, n_scalar, n_vector):
    fields = [{"fieldName": "id", "dataType": "Int64", "isPrimary": True, "elementTypeParams": {}}]
    fields.append({"fieldName": "vec", "dataType": "FloatVector", "elementTypeParams": {"dim": "8"}})
    for i in range(n_scalar):
        fields.append({"fieldName": "f%d" % i, "dataType": "Int64", "elementTypeParams": {}})
    for i in range(n_vector):
        fields.append({"fieldName": "v%d" % i, "dataType": "FloatVector",
                       "elementTypeParams": {"dim": "8"}})
    return safe_request("POST", "collections+create",
                        {"collectionName": name, "schema": {"fields": fields}})


def main():
    findings = []
    # total field count: 1 pk + n_scalar => 64 boundary at n_scalar=63
    for n, note in [(62, "63 total fields"), (63, "64 total (at max, legal)"), (64, "65 total (max+1)")]:
        name = "r2fc_%d" % n
        drop_collection(name)
        s, b, raw = mkcol(name, n, 0)
        cd = code_of(b)
        print("%-24s -> code=%-5s %s" % (note, cd, raw[:120]))
        if cd == 0 and n == 64:
            findings.append("65 fields accepted (max 64)")
        if cd != 0 and n == 62:
            findings.append("%s rejected although <= 64" % note)
    # vector fields: max 4
    for nv, note in [(4, "4 vector fields (at max)"), (5, "5 vector fields (max+1)")]:
        name = "r2fv_%d" % nv
        drop_collection(name)
        s, b, raw = mkcol(name, 0, nv)
        cd = code_of(b)
        print("%-24s -> code=%-5s %s" % (note, cd, raw[:120]))
        if cd == 0 and nv == 5:
            findings.append("5 vector fields accepted (max 4)")
    # duplicate field names
    drop_collection("r2dup")
    fields = [
        {"fieldName": "id", "dataType": "Int64", "isPrimary": True, "elementTypeParams": {}},
        {"fieldName": "vec", "dataType": "FloatVector", "elementTypeParams": {"dim": "8"}},
        {"fieldName": "dup", "dataType": "Int64", "elementTypeParams": {}},
        {"fieldName": "dup", "dataType": "Int64", "elementTypeParams": {}},
    ]
    s, b, raw = safe_request("POST", "collections+create",
                             {"collectionName": "r2dup", "schema": {"fields": fields}})
    cd = code_of(b)
    print("%-24s -> code=%-5s %s" % ("duplicate field names", cd, raw[:120]))
    if cd == 0:
        findings.append("duplicate field names accepted in schema")

    for n in ("r2fc_62", "r2fc_63", "r2fc_64", "r2fv_4", "r2fv_5", "r2dup"):
        try:
            drop_collection(n)
        except Exception:
            pass

    if findings:
        for f in findings:
            print("FINDING: " + f)
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)")
    else:
        print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
