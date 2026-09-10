#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script (R2)
Target: milvus v2.6.16
Attack: tri-state consistency — for collectionName on describe (required) and
dbName on insert (optional): omitted vs "" vs null must be rejected for required
params in ALL three present-forms, and "" / null must NOT be silently treated as
"omitted" default (default db) for optional dbName (isolation hole).
Constraint: milvus_behavioral_envelope_002 (missing required -> 1802),
milvus_state_collections_create_002 family (dbName routing).
Control: valid describe succeeds; insert without dbName succeeds (default db).
# exploration_target: novel_candidate
# shape_id: tri_state_omitted_empty_null
# shape_type: null_handling
"""
import os, sys, json

_sd = os.environ.get("TESTVDB_SCRIPTS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "scripts")
sys.path.insert(0, _sd)
from runtime import get_runtime
rt = get_runtime()

COLL = "bnd_r2_tri_25"
DIM = 8

def body_code(raw):
    try:
        return json.loads(raw).get("code", -1)
    except Exception:
        return -1

def main():
    ok, err = rt.setup_default(COLL, DIM)
    if not ok:
        print(f"VERDICT: SCRIPT_ERROR — setup: {err}")
        sys.exit(2)
    try:
        # control: valid describe
        s, raw = rt.request("POST", "describe_collection",
                            {"collectionName": COLL})
        print(f"[control describe] {s} {raw[:120]}")
        if body_code(raw) != 0:
            print("VERDICT: SCRIPT_ERROR — control failed")
            sys.exit(2)

        defect = False
        # A. required collectionName: omitted vs "" vs null — all must be rejected
        for label, body in [
            ("describe name omitted", {}),
            ("describe name=''", {"collectionName": ""}),
            ("describe name=null", {"collectionName": None}),
        ]:
            s, raw = rt.request("POST", "describe_collection", body)
            bc = body_code(raw)
            v = rt.expect_rejected(s, raw, setup_ok=True)
            print(f"[{label}] {s} code={bc} {raw[:160]} -> {v}")
            if v != "NO_DEFECT":
                # accepted or unjudgeable required-name present-form
                if v == "DEFECT_FOUND":
                    defect = True

        # B. optional dbName='' / null on insert — must NOT route to default silently
        # (behavioral consistency probe; empty dbName != omitted dbName)
        row = {"vector": [0.1] * DIM}
        for label, extra in [("insert dbName=''", {"dbName": ""}),
                             ("insert dbName=null", {"dbName": None})]:
            body = {"collectionName": COLL, "data": [row], **extra}
            s, raw = rt.request("POST", "insert_points", body)
            bc = body_code(raw)
            print(f"[{label}] {s} code={bc} {raw[:160]}")
            if label.endswith("''") and bc == 0:
                # empty dbName accepted and routed to default = silent coercion
                print(f"  -> note: empty dbName treated as default (candidate inconsistency)")
        print("VERDICT: DEFECT_FOUND" if defect else "VERDICT: NO_DEFECT")
        sys.exit(1 if defect else 0)
    finally:
        rt.drop_collection(COLL)

if __name__ == "__main__":
    main()
