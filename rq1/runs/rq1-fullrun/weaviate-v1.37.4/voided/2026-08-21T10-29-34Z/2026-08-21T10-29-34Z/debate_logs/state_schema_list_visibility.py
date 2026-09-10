#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB State Attack Script
Target: weaviate v1.37.4
Chunk: POST /schema
Attack: create class then verify immediate presence in GET /schema (list registry).
        A freshly created class must be listed by the schema registry (GET /schema)
        with its name and vectorConfig, not silently absent (eventual / lost registry
        update). Registry-listing visibility is a distinct read path from GraphQL.
        After DELETE, the class must be absent from the same list (registry removal).
Constraint: contract POST /schema + GET /schema "Retrieves the definitions of all
        collections" (OpenAPI) — registry consistency invariant
exploration_target: regression
shape_id: schema_list_visibility
shape_type: state_consistency
generalized_from: POST /schema -> GET /schema registry read path
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

CLS = "StateSchemaListVisibility"

def _list_class_names():
    """Return list of class names from GET /schema, or None on failure."""
    ls, body, raw = rt.request("GET", "list_schema")
    if ls != 200:
        return None, raw
    names = []
    if isinstance(body, dict):
        classes = body.get("classes") or body.get("Classes") or []
        for c in classes:
            if isinstance(c, dict):
                nm = c.get("class") or c.get("name")
                if nm:
                    names.append(nm)
    return names, raw

def cleanup():
    try:
        rt.request("DELETE", "drop_schema", path_params={"name": CLS})
    except Exception as e:
        print(f"Cleanup warning: {e}")

def main():
    # Arrange: create class.
    payload = {
        "class": CLS,
        "vectorizer": "none",
        "vectorIndexType": "hnsw",
        "vectorIndexConfig": {"distance": "cosine"}
    }
    s1, _, raw1 = rt.request("POST", "create_schema", payload)
    print(f"Create Status: {s1} raw={raw1[:160]}")
    if s1 not in (200, 201):
        print("VERDICT: SCRIPT_ERROR — create failed: " + str(raw1)[:200])
        sys.exit(2)

    # Act 1: class must appear in GET /schema registry immediately.
    names, lraw = _list_class_names()
    print(f"List schema Status raw: {lraw[:300]}")
    if names is None:
        print(f"VERDICT: SCRIPT_ERROR — GET /schema failed: " + str(lraw)[:200])
        sys.exit(2)
    print(f"Registry contains {len(names)} classes; {CLS} present={CLS in names}")
    if CLS not in names:
        print("DEFECT signal — freshly created class missing from GET /schema registry")
        print("VERDICT: DEFECT_FOUND")
        sys.exit(1)

    # Act 2: delete then re-check registry removal.
    ds, _, draw = rt.request("DELETE", "drop_schema", path_params={"name": CLS})
    print(f"Delete Status: {ds} raw={draw[:120]}")
    if ds not in (200, 204):
        print("VERDICT: SCRIPT_ERROR — delete failed: " + str(draw)[:200])
        sys.exit(2)

    names2, lraw2 = _list_class_names()
    print(f"Post-delete registry raw: {lraw2[:200]}")
    if names2 is None:
        print(f"VERDICT: SCRIPT_ERROR — GET /schema after delete failed")
        sys.exit(2)
    print(f"Post-delete registry: {CLS} still-present={CLS in names2}")
    if CLS in names2:
        print("DEFECT signal — deleted class still listed in GET /schema registry")
        print("VERDICT: DEFECT_FOUND")
        sys.exit(1)

    print("Schema registry consistently reflects create (present) and delete (absent)")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
