#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script (R2)
Target: milvus v2.6.16
Attack: zero / negative shards at collections/create (params.shardsNum=0 / -1).
Constraint: milvus_range_collections_create_005 (numShards <= 16 max bound; a minimum
of 1 is implied — 0 or negative shard counts are structurally impossible and must be
rejected, not clamped). Live R2 run: dim=0/-1 correctly rejected (control family);
shardsNum=0 and -1 both returned code 0 => suspected Type1_IllegalSuccess.
Control: valid dimension=8 / shards default create succeeds.
# exploration_target: novel_candidate
# shape_id: numeric_zero_negative
# shape_type: numeric_boundary
"""
import os, sys, json

_sd = os.environ.get("TESTVDB_SCRIPTS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "scripts")
sys.path.insert(0, _sd)
from runtime import get_runtime
rt = get_runtime()

def code(raw):
    try:
        return json.loads(raw).get("code", -1)
    except Exception:
        return -1

def drop(n):
    try:
        rt.drop_collection(n)
    except Exception:
        pass

def main():
    # control: valid create
    s, raw = rt.request("POST", "create_collection",
                        {"collectionName": "bnd_r2_ctrl_20", "dimension": 8})
    print(f"[control dim=8] {s} {raw[:150]}")
    if code(raw) != 0:
        print("VERDICT: SCRIPT_ERROR — control create failed")
        sys.exit(2)
    drop("bnd_r2_ctrl_20")

    # same-family control: dim=-1 rejected (live baseline proves validator active)
    s, raw = rt.request("POST", "create_collection",
                        {"collectionName": "bnd_r2_z_20b", "dimension": -1})
    print(f"[control dim=-1] {s} {raw[:150]}")

    defect = False
    for label, body in [
        ("shardsNum=0", {"collectionName": "bnd_r2_z_20c", "dimension": 8,
                         "params": {"shardsNum": 0}}),
        ("shardsNum=-1", {"collectionName": "bnd_r2_z_20d", "dimension": 8,
                          "params": {"shardsNum": -1}}),
    ]:
        s, raw = rt.request("POST", "create_collection", body)
        c = code(raw)
        print(f"[create {label}] {s} code={c} {raw[:200]}")
        if c == 0:
            # accepted: verify persistence via describe (shard num echoed?)
            ds, draw = rt.request("POST", "describe_collection",
                                  {"collectionName": body["collectionName"]})
            print(f"  [describe after accept] {ds} {draw[:300]}")
            defect = True
        drop(body["collectionName"])

    print("VERDICT: DEFECT_FOUND" if defect else "VERDICT: NO_DEFECT")
    sys.exit(1 if defect else 0)

if __name__ == "__main__":
    main()
