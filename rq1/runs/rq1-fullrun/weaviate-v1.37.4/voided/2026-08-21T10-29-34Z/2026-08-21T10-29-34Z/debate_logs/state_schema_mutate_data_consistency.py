#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB State Attack Script
Target: weaviate v1.37.4
Chunk: POST /schema
Attack: schema mutation on existing data (add_property POST /schema/{className}/properties).
        After creating a class + inserting objects, add a new property via /properties.
        Requirement: existing data must remain intact (count preserved, objects retrievable)
        and the new property must appear in the class definition. Any silent data-loss /
        count mutation / missing property is a state-inconsistency defect.
        (Runtime PATHS expose no update_schema key for PUT /schema/{className}; add_property
         is the sanctioned schema-mutation path and exercises the same state-consistency plane.)
Constraint: contract POST /schema + POST /schema/{className}/properties
        "Adds a new property definition to an existing collection definition" (OpenAPI)
exploration_target: regression
shape_id: schema_mutation_data_consistency
shape_type: state_consistency
generalized_from: POST /schema -> add_property mutation path
Blindspot: BS-03 Concurrency Blindness
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

CLS = "StateSchemaMutateData"

def cleanup():
    try:
        rt.request("DELETE", "drop_schema", path_params={"name": CLS})
    except Exception as e:
        print(f"Cleanup warning: {e}")

def _class_count():
    """GraphQL aggregate count; returns int or None if unparsable."""
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
    # Arrange: create class with a text property + insert 3 objects.
    payload = {
        "class": CLS,
        "vectorizer": "none",
        "vectorIndexType": "hnsw",
        "vectorIndexConfig": {"distance": "cosine"},
        "properties": [
            {"name": "idx", "dataType": ["int"]}
        ]
    }
    s1, _, raw1 = rt.request("POST", "create_schema", payload)
    print(f"Create Status: {s1} raw={raw1[:160]}")
    if s1 not in (200, 201):
        print("VERDICT: SCRIPT_ERROR — create failed: " + str(raw1)[:200])
        sys.exit(2)

    objs = [{"class": CLS, "properties": {"idx": i}} for i in range(3)]
    bs, _, braw = rt.request("POST", "batch_objects", {"objects": objs})
    print(f"Batch insert Status: {bs} raw={braw[:200]}")

    cnt_before, _ = _class_count()
    print(f"Count before add_property: {cnt_before}")
    if cnt_before is None or cnt_before != 3:
        print("DEFECT signal — expected count=3 before mutation, got " + str(cnt_before))
        print("VERDICT: DEFECT_FOUND")
        sys.exit(1)

    # Act: add a new property to the class (schema mutation on existing data).
    prop = {"name": "extra", "dataType": ["text"]}
    as_, _, araw = rt.request("POST", "add_property", prop, path_params={"name": CLS})
    print(f"Add property Status: {as_} raw={araw[:200]}")
    if as_ not in (200, 204):
        print("VERDICT: SCRIPT_ERROR — add_property failed: " + str(araw)[:200])
        sys.exit(2)

    # Verify: existing data intact after schema mutation (no data loss).
    cnt_after, _ = _class_count()
    print(f"Count after add_property: {cnt_after}")
    if cnt_after != 3:
        print(f"DEFECT signal — data count changed after mutation (before=3, after={cnt_after})")
        print("VERDICT: DEFECT_FOUND")
        sys.exit(1)

    # Verify: new property present in the class definition.
    gs, body, gr = rt.request("GET", "describe_schema", path_params={"name": CLS})
    print(f"After-mutation describe Status: {gs} raw={gr[:200]}")
    props = None
    if isinstance(body, dict):
        if isinstance(body.get("properties"), list):
            props = body.get("properties")
        else:
            for key in ("class", "Class", "objectClass"):
                if isinstance(body.get(key), dict):
                    props = body[key].get("properties")
                    break
        if props is None:
            classes = body.get("classes") or body.get("Classes") or []
            for c in classes:
                if isinstance(c, dict) and c.get("class") == CLS:
                    props = c.get("properties")
                    break
    if not isinstance(props, list):
        print(f"VERDICT: SCRIPT_ERROR — could not read properties after mutation")
        sys.exit(2)
    names = [p.get("name") for p in props if isinstance(p, dict)]
    print(f"Properties readback: {names}")
    if "extra" not in names:
        print(f"DEFECT signal — added property 'extra' missing from class definition {names}")
        print("VERDICT: DEFECT_FOUND")
        sys.exit(1)

    print("Schema mutation preserved data (count=3) and persisted the new property")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
