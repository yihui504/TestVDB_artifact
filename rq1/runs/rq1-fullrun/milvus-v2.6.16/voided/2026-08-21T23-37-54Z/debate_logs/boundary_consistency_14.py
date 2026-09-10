#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.16
Attack: boundary / missing-required + dbName omission semantics on
collections+describe (envelope + required-parameter family)
Constraint: milvus_behavioral_envelope_002 (missing required -> HTTP 200 + 1802)

This unit: collections+describe with EMPTY body (missing required collectionName).
Expected: rejected (code 1802 'missing required parameters').
If accepted (code 0) => Type1.
# exploration_target: regression
# shape_id: missing_required
# shape_type: type_confusion
"""
import os, sys

_sd = os.environ.get("TESTVDB_SCRIPTS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "scripts")
sys.path.insert(0, _sd)
from runtime import get_runtime
rt = get_runtime()

def main():
    status, raw = rt.request("POST", "describe_collection", {})
    print(f"Status: {status}\nRaw: {raw[:400]}")
    v = rt.expect_rejected(status, raw, setup_ok=True)
    print(f"VERDICT: {v}")
    sys.exit(0 if v == "NO_DEFECT" else 1 if v == "DEFECT_FOUND" else 2)

if __name__ == "__main__":
    main()
