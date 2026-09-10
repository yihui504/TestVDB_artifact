#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script R2
Target: milvus v2.6.17
Attack: collections+drop_function json-tag quirk boundary: contract says the request struct
        expects capital-F 'FunctionName' (NOT 'functionName'). Probe both spellings, empty,
        missing, and nonexistent function drop semantics.
Constraint: endpoint_registry collections+drop_function doc_quote (json tag quirk)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import safe_request, code_of, create_collection, drop_collection

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

COL = "r2fn_009"


def main():
    drop_collection(COL)
    s, b, raw = create_collection(COL)
    print("setup:", code_of(b))
    findings = []

    for body, note in [
        ({"collectionName": COL, "FunctionName": "no_such_fn"}, "capital-F FunctionName (per contract quirk)"),
        ({"collectionName": COL, "functionName": "no_such_fn"}, "lowercase functionName"),
        ({"collectionName": COL, "FunctionName": ""}, "empty FunctionName"),
        ({"collectionName": COL}, "missing name key entirely"),
        ({"collectionName": COL, "FunctionName": 123}, "non-string FunctionName (int)"),
    ]:
        s, b, raw = safe_request("POST", "collections+drop_function", body)
        cd = code_of(b)
        print("%-46s -> code=%-5s %s" % (note, cd, raw[:140]))

    # key semantic: does lowercase 'functionName' get silently ignored (-> 1802 missing) or work?
    s_cap, b_cap, _ = safe_request("POST", "collections+drop_function",
                                   {"collectionName": COL, "FunctionName": "no_such_fn"})
    s_low, b_low, _ = safe_request("POST", "collections+drop_function",
                                   {"collectionName": COL, "functionName": "no_such_fn"})
    if code_of(b_low) == code_of(b_cap) and code_of(b_cap) not in (1802,):
        print("NOTE: lowercase fieldName behaves same as capital-F (both reach lookup)")
    if code_of(b_low) == 0 and code_of(b_cap) == 1802:
        findings.append("lowercase functionName works but contract documents capital-F quirk")
    if code_of(b_cap) == 0:
        findings.append("drop_function on NONEXISTENT function returns code 0 (silent success, no not-found error)")

    try:
        drop_collection(COL)
    except Exception:
        pass

    if findings:
        for f in findings:
            print("FINDING: " + f)
        print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics)")
    else:
        print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
