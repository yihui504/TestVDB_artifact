#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.16
Attack: boundary / dbName nonexistent matrix (read path — consistency check
against write path's code 800).
Constraint: milvus_state_collections_create_002 (family: dbName state validation)

This unit: databases+describe with dbName=bnd_nodb_9527. The create path
rejects nonexistent dbName with 800; consistency demands the read path reject
likewise. If describe silently returns data (or code 0) for a nonexistent DB
while create rejects, that is an inconsistent dbName surface (Type2 candidate).
Expected: rejected (code 800).
# exploration_target: novel_candidate
# shape_id: dbname_matrix
# shape_type: semantic_drift
"""
import os, sys

_sd = os.environ.get("TESTVDB_SCRIPTS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "scripts")
sys.path.insert(0, _sd)
from runtime import get_runtime
rt = get_runtime()

def main():
    status, raw = rt.request("POST", "databases+describe",
                             {"dbName": "bnd_nodb_9527"})
    print(f"Status: {status}\nRaw: {raw[:400]}")
    v = rt.expect_rejected(status, raw, setup_ok=True)
    print(f"VERDICT: {v}")
    sys.exit(0 if v == "NO_DEFECT" else 1 if v == "DEFECT_FOUND" else 2)

if __name__ == "__main__":
    main()
