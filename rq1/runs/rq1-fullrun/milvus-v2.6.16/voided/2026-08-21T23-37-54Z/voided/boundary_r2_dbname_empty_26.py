#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script (R2)
Target: milvus v2.6.16
Attack: dbName="" / dbName=null across read and write endpoints — empty dbName must
be rejected (naming rules) and must NOT be silently coerced to the default database
(cross-db isolation hole: a "" db that behaves like "default" would let clients
target wrong namespace). Also collections+list dbName="".
Constraint: milvus_state_collections_create_002 (nonexistent dbName -> 800;
empty dbName is not a valid db name and must error, not fall back to default).
Control: dbName omitted -> code 0 on all four endpoints.
# exploration_target: novel_candidate
# shape_id: dbname_empty_coercion
# shape_type: null_handling
"""
import os, sys, json

_sd = os.environ.get("TESTVDB_SCRIPTS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "scripts")
sys.path.insert(0, _sd)
from runtime import get_runtime
rt = get_runtime()

COLL = "bnd_r2_db_26"
DIM = 8

def code(raw):
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
        # control: dbName omitted -> success everywhere
        controls = [
            ("has-alias-list", "aliases+list", {}),
            ("describe", "describe_collection", {"collectionName": COLL}),
            ("insert", "insert_points",
             {"collectionName": COLL, "data": [{"vector": [0.1] * DIM}]}),
        ]
        ctrl_ok = True
        for label, key, body in controls:
            s, raw = rt.request("POST", key, body)
            c = code(raw)
            print(f"[control {label} no dbName] {s} code={c}")
            ctrl_ok = ctrl_ok and c == 0
        if not ctrl_ok:
            print("VERDICT: SCRIPT_ERROR — control failed")
            sys.exit(2)

        # R1 covered dbName=no_such_db (nonexistent). R2 target: "" and null.
        defect = False
        attacks = [
            
            ("describe dbName=''", "describe_collection",
             {"collectionName": COLL, "dbName": ""}),
            ("insert dbName=''", "insert_points",
             {"collectionName": COLL, "dbName": "",
              "data": [{"vector": [0.2] * DIM}]}),
            ("create dbName=''", "create_collection",
             {"collectionName": "bnd_r2_db_26_x", "dbName": "", "dimension": 8}),
            ("describe dbName=null", "describe_collection",
             {"collectionName": COLL, "dbName": None}),
        ]
        for label, key, body in attacks:
            s, raw = rt.request("POST", key, body)
            c = code(raw)
            v = rt.expect_rejected(s, raw, setup_ok=True)
            print(f"[{label}] {s} code={c} {raw[:180]} -> {v}")
            if v == "DEFECT_FOUND":
                defect = True
        try:
            rt.drop_collection("bnd_r2_db_26_x")
        except Exception:
            pass
        print("VERDICT: DEFECT_FOUND" if defect else "VERDICT: NO_DEFECT")
        sys.exit(1 if defect else 0)
    finally:
        rt.drop_collection(COLL)

if __name__ == "__main__":
    main()
