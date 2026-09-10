#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB State Attack Script
Target: weaviate v1.37.4
Chunk: POST /schema
Attack: create class then immediately query visibility via GraphQL aggregate count.
        A newly-created empty class must be visible to GraphQL immediately (count=0,
        not "class not found"). Inconsistent/eventual schema visibility is a defect.
Constraint: contract POST /schema (schema) + GET /schema state visibility invariant
        (contract lacks explicit state_invariants; inferred from OpenAPI "Create collection")
exploration_target: regression
shape_id: schema_query_visibility
shape_type: state_consistency
generalized_from: POST /schema -> graphql read path
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

CLS = "StateSchemaVisibility"

def cleanup():
    try:
        rt.request("DELETE", "drop_schema", path_params={"name": CLS})
    except Exception as e:
        print(f"Cleanup warning: {e}")

def main():
    # Arrange: create empty class with a non-named vectorizer so object insertion is possible.
    payload = {
        "class": CLS,
        "vectorizer": "none",
        "vectorIndexType": "hnsw",
        "vectorIndexConfig": {"distance": "cosine"}
    }
    status, _body, raw = rt.request("POST", "create_schema", payload)
    print(f"Status: {status}")
    print(f"Raw: {raw}")
    if status not in (200, 201):
        print("VERDICT: SCRIPT_ERROR — create_schema failed: " + str(raw)[:200])
        sys.exit(2)

    # Act: GraphQL aggregate count on the class immediately after create.
    q = '{"query": "{ Aggregate { %s { meta { count } } } }"}' % CLS
    qs, qbody, qraw = rt.request("POST", "graphql", q)
    print(f"GraphQL aggregate Status: {qs}")
    print(f"GraphQL aggregate Raw: {qraw}")

    if qs != 200:
        # Class not visible / query failed right after creation => state inconsistency.
        print(f"DEFECT signal — class not visible to GraphQL right after create (status={qs})")
        print("VERDICT: DEFECT_FOUND")
        sys.exit(1)

    # Parse nested count {"data":{"Aggregate":{"<Class>":[{"meta":{"count":N}}]}}}
    count_val = None
    if qbody is not None and isinstance(qbody, dict):
        aggr = qbody.get("data", {}).get("Aggregate", {})
        arr = aggr.get(CLS)
        if isinstance(arr, list) and arr and isinstance(arr[0], dict):
            count_val = arr[0].get("meta", {}).get("count")
    print(f"Aggregate count readback: {count_val}")

    if count_val is None:
        print("DEFECT signal — aggregate count missing/unparsable for a valid empty class")
        print("VERDICT: DEFECT_FOUND")
        sys.exit(1)

    if count_val != 0:
        # A fresh class must have 0 objects visible.
        print(f"DEFECT signal — expected count=0 for fresh class, got {count_val}")
        print("VERDICT: DEFECT_FOUND")
        sys.exit(1)

    print("Class visible to GraphQL immediately after create with count=0")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
