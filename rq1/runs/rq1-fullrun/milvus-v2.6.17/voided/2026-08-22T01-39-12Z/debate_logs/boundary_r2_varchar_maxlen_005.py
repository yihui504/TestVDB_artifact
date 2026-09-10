#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script R2
Target: milvus v2.6.17
Attack: VarChar max_length boundary + value length enforcement (schema decl vs data ingest)
Constraint: milvus_range_collections_create_004 (max_length <= 65535)
R1 did not cover this. Probe:
  - schema max_length 65535 (max) / 65536 (max+1) declaration
  - max_length 0 / negative / non-numeric string
  - ingest value longer than declared max_length (should be rejected per-field)
  - unicode value whose BYTE length exceeds max but char count does not
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import safe_request, code_of, load_collection, drop_collection

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def mkcol(name, max_len):
    fields = [
        {"fieldName": "id", "dataType": "Int64", "isPrimary": True, "elementTypeParams": {}},
        {"fieldName": "vec", "dataType": "FloatVector", "elementTypeParams": {"dim": "8"}},
        {"fieldName": "text", "dataType": "VarChar", "elementTypeParams": {"max_length": str(max_len)}},
    ]
    return safe_request("POST", "collections+create",
                        {"collectionName": name, "schema": {"fields": fields}})


def main():
    findings = []
    cases = [
        ("r2vc_max", 65535, "max_length=65535 (at max)"),
        ("r2vc_over", 65536, "max_length=65536 (max+1)"),
        ("r2vc_zero", 0, "max_length=0"),
        ("r2vc_neg", -1, "max_length=-1"),
        ("r2vc_junk", "abc", "max_length='abc' (non-numeric)"),
        ("r2vc_missing", None, "max_length missing"),
    ]
    created = []
    for name, ml, note in cases:
        if ml is None:
            fields = [
                {"fieldName": "id", "dataType": "Int64", "isPrimary": True, "elementTypeParams": {}},
                {"fieldName": "vec", "dataType": "FloatVector", "elementTypeParams": {"dim": "8"}},
                {"fieldName": "text", "dataType": "VarChar", "elementTypeParams": {}},
            ]
            s, b, raw = safe_request("POST", "collections+create",
                                     {"collectionName": name, "schema": {"fields": fields}})
        else:
            s, b, raw = mkcol(name, ml)
        cd = code_of(b)
        print("%-34s -> code=%-5s %s" % (note, cd, raw[:130]))
        if cd == 0:
            created.append(name)
            if name in ("r2vc_over", "r2vc_zero", "r2vc_neg", "r2vc_junk"):
                findings.append("VarChar max_length=%r ACCEPTED at schema (expected reject)" % ml)

    # ingest over-length value into the at-max collection
    if "r2vc_max" in created:
        load_collection("r2vc_max")
        s, b, raw = safe_request("POST", "entities+insert", {
            "collectionName": "r2vc_max",
            "data": [{"id": 1, "vec": [0.1] * 8, "text": "a" * 65536}]})
        cd = code_of(b)
        print("insert value len 65536 (decl 65535) -> code=%s %s" % (cd, raw[:130]))
        if cd == 0:
            findings.append("VarChar value 65536 chars accepted though max_length=65535")

        # unicode: 21846 chars * 3 bytes = 65544 bytes, chars < 65535
        s, b, raw = safe_request("POST", "entities+insert", {
            "collectionName": "r2vc_max",
            "data": [{"id": 2, "vec": [0.1] * 8, "text": "密" * 21846}]})
        cd = code_of(b)
        n = None
        if isinstance(b, dict):
            n = (b.get("data") or {}).get("insertCount")
        print("insert 21846 CJK chars (65544 bytes) -> code=%s insertCount=%s %s" % (cd, n, raw[:130]))
        if cd == 0:
            print("NOTE: char-count semantics (bytes would be 65544 > 65535)")

    for name in created + ["r2vc_over", "r2vc_zero", "r2vc_neg", "r2vc_junk", "r2vc_missing"]:
        try:
            drop_collection(name)
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
