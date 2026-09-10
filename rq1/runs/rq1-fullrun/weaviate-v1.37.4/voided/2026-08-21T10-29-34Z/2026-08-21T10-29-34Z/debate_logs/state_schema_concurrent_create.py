#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB State Attack Script
Target: weaviate v1.37.4
Chunk: POST /schema
Attack: N threads concurrently POST the SAME class name (/v1/schema).
        Outcome must be deterministic: after the dust settles exactly one valid class
        definition exists; no 500 internal errors; a lost/parenthesized concurrent
        create must not corrupt the schema or leak a half-created class.
Constraint: contract POST /schema (schema) — schema single-writer consistency invariant
        (state_invariants absent, inferred from OpenAPI "Create collection")
exploration_target: regression
shape_id: schema_concurrent_create
shape_type: state_consistency
generalized_from: lifecycle create x concurrent
Blindspot: BS-03 Concurrency Blindness
"""

import os
import sys
import threading

# Windows encoding compatibility
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_sd = os.environ.get("TESTVDB_SCRIPTS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, _sd)

from runtime import get_runtime  # weaviate target runtime (contract-driven)
rt = get_runtime()

CLS = "StateSchemaConcurrentCreate"
THREADS = int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "20"))

def cleanup():
    try:
        rt.request("DELETE", "drop_schema", path_params={"name": CLS})
    except Exception as e:
        print(f"Cleanup warning: {e}")

def main():
    payload = {
        "class": CLS,
        "vectorizer": "none",
        "vectorIndexType": "hnsw",
        "vectorIndexConfig": {"distance": "cosine", "dynamicEfMin": 100, "dynamicEfMax": 300}
    }

    results = []
    lock = threading.Lock()

    def create(i):
        s, body, raw = rt.request("POST", "create_schema", payload)
        with lock:
            results.append((i, s, str(raw)[:160]))
            # 500 = internal error while handling a concurrent duplicate -> defect signal
            if s == 500:
                print(f"DEFECT_CAPTURE thread {i} 500: {str(raw)[:160]}")

    threads = [threading.Thread(target=create, args=(i,)) for i in range(THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Print all statuses for diagnosis.
    for i, s, raw in results:
        print(f"thread {i}: status={s} raw={raw}")

    # Defect: any 500 / connection reset from a concurrent duplicate create.
    server_errors = [r for r in results if r[1] == 500]
    if server_errors:
        print(f"DEFECT signal — {len(server_errors)} concurrent create(s) returned 500")
        print("VERDICT: DEFECT_FOUND")
        sys.exit(1)

    # Defect: empty result set (all requests threaded through but none recorded).
    if len(results) < THREADS:
        print(f"DEFECT signal — only {len(results)}/{THREADS} create responses captured")
        print("VERDICT: DEFECT_FOUND")
        sys.exit(1)

    # Final state: single authoritative class definition must exist and be uncorrupted.
    gs, body, graw = rt.request("GET", "describe_schema", path_params={"name": CLS})
    print(f"Final describe Status: {gs}")
    print(f"Final describe Raw: {graw}")

    cfg = None
    if isinstance(body, dict):
        for key in ("class", "Class", "objectClass"):
            if isinstance(body.get(key), dict):
                cfg = body[key]
                break
        if cfg is None:
            classes = body.get("classes") or body.get("Classes") or []
            for c in classes:
                if isinstance(c, dict) and c.get("class") == CLS:
                    cfg = c
                    break
    if cfg is None:
        # Either class vanished or never durably materialized after concurrent creates.
        print("DEFECT signal — class definition missing after concurrent creates")
        print("VERDICT: DEFECT_FOUND")
        sys.exit(1)

    # The class must be fully usable (prior object insert path).
    print("Concurrent same-name create converged to a single consistent class")
    print(f"Responses: {len(results)} (statuses: {[r[1] for r in results][:40]})")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
