#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB State Attack Script
Target: weaviate v1.37.4
Chunk: POST /schema
Attack: delete class then recreate the SAME name — state restoration integrity.
        Sequence: create -> insert object -> DELETE class -> recreate same class name
        -> old data must be gone, new class usable, describe must reflect the NEW
        definition (no stale/merged config from the deleted instance).
Constraint: contract POST /schema + DELETE /schema/{className} "permanently deletes all
        data" (OpenAPI) — recreate-same-name state isolation invariant
exploration_target: regression
shape_id: schema_delete_recreate
shape_type: state_consistency
generalized_from: create -> delete -> recreate lifecycle
Blindspot: BS-03 Concurrency Blindness
"""

import os
import sys
import uuid

# Windows encoding compatibility
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_sd = os.environ.get("TESTVDB_SCRIPTS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, _sd)

from runtime import get_runtime  # weaviate target runtime (contract-driven)
rt = get_runtime()

CLS = "StateSchemaDeleteRecreate"

def cleanup():
    try:
        rt.request("DELETE", "drop_schema", path_params={"name": CLS})
    except Exception as e:
        print(f"Cleanup warning: {e}")

def _class_count():
    """GraphQL aggregate count for CLS; returns int or None if unparsable."""
    q = '{"query": "{ Aggregate { %s { meta { count } } } }"}' % CLS
    qs, body, raw = rt.request("POST", "graphql", q)
    if qs != 200:
        return None, raw
    if isinstance(body, dict):
        arr = body.get("data", {}).get("Aggregate", {}).get(CLS)
        if isinstance(arr, list) and arr and isinstance(arr[0], dict):
            return arr[0].get("meta", {}).get("count"), raw
    return None, raw

def main():
    # --- Create with a distinct identifier config ---
    first_cfg = {
        "class": CLS,
        "vectorizer": "none",
        "vectorIndexType": "hnsw",
        "vectorIndexConfig": {"distance": "cosine", "dynamicEfMin": 100, "dynamicEfMax": 900}
    }
    s1, _, raw1 = rt.request("POST", "create_schema", first_cfg)
    print(f"First create Status: {s1} raw={raw1[:120]}")
    if s1 not in (200, 201):
        print("VERDICT: SCRIPT_ERROR — first create failed: " + str(raw1)[:200])
        sys.exit(2)

    # Insert an object so we can verify deletion clears it.
    oid = str(uuid.uuid4())
    obj = {"class": CLS, "id": oid, "properties": {"text": "stale-data"}}
    os_, _, oraw = rt.request("POST", "create_object", obj)
    print(f"Object insert Status: {os_} raw={oraw[:120]}")
    if os_ not in (200, 201):
        print("VERDICT: SCRIPT_ERROR — object insert failed: " + str(oraw)[:200])
        sys.exit(2)

    # --- Delete class (permanently deletes all data) ---
    ds, _, draw = rt.request("DELETE", "drop_schema", path_params={"name": CLS})
    print(f"Delete class Status: {ds} raw={draw[:120]}")
    if ds not in (200, 204):
        print("VERDICT: SCRIPT_ERROR — delete class failed: " + str(draw)[:200])
        sys.exit(2)

    # --- Recreate same name with a DIFFERENT config (dynamicEfMax 300) ---
    second_cfg = {
        "class": CLS,
        "vectorizer": "none",
        "vectorIndexType": "hnsw",
        "vectorIndexConfig": {"distance": "cosine", "dynamicEfMin": 100, "dynamicEfMax": 300}
    }
    s2, _, raw2 = rt.request("POST", "create_schema", second_cfg)
    print(f"Second create Status: {s2} raw={raw2[:120]}")
    if s2 not in (200, 201):
        print("VERDICT: SCRIPT_ERROR — recreate failed: " + str(raw2)[:200])
        sys.exit(2)

    # --- Verify old data is gone: recreated class must expose count=0 (data isolation) ---
    cnt, craw = _class_count()
    print(f"Recreated class aggregate raw: {craw[:160]}")
    print(f"Recreated class count: {cnt} (expected 0 for isolated recreate)")
    if cnt is None:
        print("DEFECT signal — recreated class not queryable / count unparsable")
        print("VERDICT: DEFECT_FOUND")
        sys.exit(1)
    if cnt != 0:
        print(f"DEFECT signal — stale data leaked on recreate: count={cnt} (expected 0)")
        print("VERDICT: DEFECT_FOUND")
        sys.exit(1)

    # --- Verify new definition read-back uses the NEW config (no stale merge) ---
    gs, body, gr = rt.request("GET", "describe_schema", path_params={"name": CLS})
    print(f"Recreate describe Status: {gs} raw={gr[:200]}")
    cfg = None
    if isinstance(body, dict):
        # weaviate describe 返回 class 对象本身（根即定义），信封形态作兼容 fallback
        cfg = body.get("vectorIndexConfig")
        if not isinstance(cfg, dict):
            for key in ("class", "Class", "objectClass"):
                if isinstance(body.get(key), dict):
                    cfg = body[key].get("vectorIndexConfig")
                    break
            if not isinstance(cfg, dict):
                classes = body.get("classes") or body.get("Classes") or []
                for c in classes:
                    if isinstance(c, dict) and c.get("class") == CLS:
                        cfg = c.get("vectorIndexConfig")
                        break
    if not isinstance(cfg, dict):
        print("VERDICT: SCRIPT_ERROR — could not read recreated vectorIndexConfig")
        sys.exit(2)

    rmax = cfg.get("dynamicEfMax")
    print(f"Recreated dynamicEfMax readback: {rmax} (expected 300)")
    if rmax != 300:
        # Stale 900 from the first instance indicates non-isolated recreate state.
        print(f"DEFECT signal — recreated config reused stale value dynamicEfMax={rmax} (expected 300)")
        print("VERDICT: DEFECT_FOUND")
        sys.exit(1)

    print("Delete-then-recreate converged to an isolated, consistent class")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
