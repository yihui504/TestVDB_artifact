#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB State Attack Script
Target: weaviate v1.37.4
Chunk: POST /schema
Attack: read-back consistency of vectorIndexConfig after POST /schema (GET /schema/{class}).
        Flavor: valid submitted values must read back equal. Any silently normalized /
        dropped / rewritten submitted field (read-back value != submitted value) is an
        inconsistent-state signal (weaviate schema silent-normalize pattern).
Constraint: contract POST /schema parameter vectorIndexConfig (go-struct defaults plane)
        + assertion weaviate_inferred_hnsw_ef_pairing_001 (Min<=Max pairing)
exploration_target: regression
shape_id: schema_readback_consistency
shape_type: state_consistency
generalized_from: contract POST /schema vectorIndexConfig
Blindspot: BS-03 Concurrency Blindness (contract lacks explicit state_invariants)
"""

import os
import sys

# Windows encoding compatibility
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_sd = os.environ.get("TESTVDB_SCRIPTS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, _sd)

from runtime import get_runtime  # weaviate target runtime (contract-driven)
rt = get_runtime()

CLS = "StateSchemaReadback"

def cleanup():
    try:
        rt.request("DELETE", "drop_schema", path_params={"name": CLS})
    except Exception as e:
        print(f"Cleanup warning: {e}")

def main():
    # Arrange: submit an explicit, fully-specified vectorIndexConfig with non-default eps.
    submitted = {
        "class": CLS,
        "vectorizer": "none",
        "vectorIndexType": "hnsw",
        "vectorIndexConfig": {
            "distance": "cosine",
            "maxConnections": 64,
            "efConstruction": 200,
            "dynamicEfMin": 250,
            "dynamicEfMax": 400,
            "flatSearchCutoff": 60000
        }
    }
    status, _body, raw = rt.request("POST", "create_schema", submitted)
    print(f"Status: {status}")
    print(f"Raw: {raw}")
    if status not in (200, 201):
        print("VERDICT: SCRIPT_ERROR — create_schema failed: " + str(raw)[:200])
        sys.exit(2)

    # Act: GET /schema/{className} and compare vectorIndexConfig read-back.
    gs, body, gr = rt.request("GET", "describe_schema", path_params={"name": CLS})
    print(f"Describe Status: {gs}")
    print(f"Describe Raw: {gr}")

    # Locate class definition in response independent of envelope shape.
    cfg = None
    if isinstance(body, dict):
        # weaviate GET /v1/schema/{name} 返回 class 对象本身（非信封）——根即 class 定义
        if body.get("vectorIndexConfig"):
            cfg = body.get("vectorIndexConfig")
        else:
            for key in ("class", "Class", "objectClass"):
                if isinstance(body.get(key), dict):
                    cfg = body[key].get("vectorIndexConfig")
                    break
            if cfg is None:
                classes = body.get("classes") or body.get("Classes") or []
                for c in classes:
                    if isinstance(c, dict) and c.get("class") == CLS:
                        cfg = c.get("vectorIndexConfig")
                        break
    if cfg is None or not isinstance(cfg, dict):
        print(f"VERDICT: SCRIPT_ERROR — could not locate vectorIndexConfig in describe body")
        sys.exit(2)

    # Compare every submitted field against read-back. Note weaviate may add defaults.
    mismatches = []
    for field, submitted_val in submitted["vectorIndexConfig"].items():
        readback_val = cfg.get(field)
        # string distance is lowercased consistently; compare exact for int fields
        if readback_val is None:
            mismatches.append(f"{field}: MISSING in readback (submitted={submitted_val})")
        elif readback_val != submitted_val:
            mismatches.append(f"{field}: submitted={submitted_val!r} != readback={readback_val!r}")

    if mismatches:
        print("DEFECT signal — read-back != submitted:")
        for m in mismatches:
            print("  " + m)
        print("VERDICT: DEFECT_FOUND")
        sys.exit(1)

    # Pairing invariant (assertion weaviate_inferred_hnsw_ef_pairing_001): Min <= Max
    mn = cfg.get("dynamicEfMin")
    mx = cfg.get("dynamicEfMax")
    if mn is not None and mx is not None and mn > mx:
        print(f"DEFECT signal — pairing violated: dynamicEfMin={mn} > dynamicEfMax={mx}")
        print("VERDICT: DEFECT_FOUND")
        sys.exit(1)

    print(f"Read-back consistent for all {len(submitted['vectorIndexConfig'])} submitted fields")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
