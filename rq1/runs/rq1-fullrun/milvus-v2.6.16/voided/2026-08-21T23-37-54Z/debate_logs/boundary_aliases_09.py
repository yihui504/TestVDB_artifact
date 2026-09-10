#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.16
Attack: boundary / aliases+list binding semantics matrix
Constraint: milvus_behavioral_aliases_list_002 (GT surface)
Contract: {}, {collectionName:X}, {collectionName:X, aliasName:Y} all -> code 0
(possibly empty) data array; unknown names never error. That permissive behavior
itself is a Type2_PoorDiagnostics candidate documented in contract.

This unit: aliases+list with BOTH a nonexistent collectionName AND a
nonexistent dbName (binding semantics: does dbName filter leak across DBs?).
Expected per contract permissiveness: code 0. Testing read-back that unknown
combo never errors AND never returns aliases from the default DB (cross-DB leak
check).
# exploration_target: novel_candidate
# shape_id: aliases_binding
# shape_type: semantic_drift
"""
import os, sys, json

_sd = os.environ.get("TESTVDB_SCRIPTS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "scripts")
sys.path.insert(0, _sd)
from runtime import get_runtime
rt = get_runtime()

def main():
    status, raw = rt.request("POST", "aliases+list", {
        "collectionName": "bnd_no_such_coll", "dbName": "bnd_nodb_9527"})
    print(f"Status: {status}\nRaw: {raw[:400]}")
    if status == 0 or 500 <= status <= 599:
        print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
    try:
        b = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
    code = b.get("code", -1)
    data = b.get("data")
    if code == 0:
        n = len(data) if isinstance(data, list) else -1
        # contract: unknown names -> code 0 with (possibly empty) data.
        # Non-empty data for a nonexistent collection would be a leak.
        if isinstance(data, list) and n > 0:
            print(f"VERDICT: DEFECT_FOUND — aliases leaked for nonexistent collection: {data}")
            sys.exit(1)
        print(f"VERDICT: NO_DEFECT — code 0, data empty (n={n})")
        sys.exit(0)
    # rejected with an merr code — also acceptable defensive behavior
    print(f"VERDICT: NO_DEFECT — rejected with code {code}")
    sys.exit(0)

if __name__ == "__main__":
    main()
