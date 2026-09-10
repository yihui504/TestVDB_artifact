#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script R2
Target: milvus v2.6.17
Attack: vector dimension boundary at exact max (32767/32768/32769) + dim 0/1/negative
Constraint: milvus_range_collections_create_001 (dim <= 32768)
R1 dimension script covered generic mismatch; exact-max boundary untested.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import safe_request, code_of, drop_collection

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def quick_create(name, dim):
    return safe_request("POST", "collections+create",
                        {"collectionName": name, "dimension": dim, "idType": "Int64",
                         "metricType": "L2"})


def main():
    findings = []
    for dim, note in [(32767, "dim 32767 (max-1)"), (32768, "dim 32768 (at max)"),
                      (32769, "dim 32769 (max+1)"), (0, "dim 0"),
                      (-1, "dim -1"), ("64", "dim '64' (string type)")]:
        name = "r2dim_%s" % str(dim).replace("-", "neg")
        drop_collection(name)
        s, b, raw = quick_create(name, dim)
        cd = code_of(b)
        print("%-24s -> code=%-5s %s" % (note, cd, raw[:130]))
        if cd == 0 and dim in (32769, 0, -1):
            findings.append("dimension=%r accepted (expected reject)" % dim)
        if cd != 0 and dim in (32767, 32768):
            findings.append("dimension=%r rejected although <= 32768" % dim)
    for d in ("32767", "32768", "32769", "0", "neg1", "64"):
        try:
            drop_collection("r2dim_" + d)
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
