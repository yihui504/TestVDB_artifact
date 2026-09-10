# script_id: semantic_collections_create_010
# strategy: behavioral_contract
# endpoint: collections+create
# Attack: qdrant_type_collections_create_009 (sparse vectors named; sparse/dense names must be disjoint)
# constraint_ids: qdrant_type_collections_create_009
# source_url: https://qdrant.tech/documentation/concepts/collections/
# doc_version: 1.18.x (versioned)
# Blindspot: BS-05 semantic contract
"""Sparse and dense vector configurations within one collection must not
share names. Creating both with name 'vec' must be rejected 400; acceptance
leads to ambiguous vector routing = Type4."""
import os, sys, time
_sd = os.environ.get("TESTVDB_SCRIPTS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "scripts")
sys.path.insert(0, _sd)
from runtime import get_runtime
rt = get_runtime()

TS = str(int(time.time()))

def cleanup(name):
    try:
        rt.request("DELETE", "drop_collection", path_params={"name": name})
    except Exception:
        pass

COLL = f"sem_cc_names_{TS}"
try:
    # same name 'vec' for dense and sparse in one create — must be rejected (names disjoint)
    s, raw = rt.request("PUT", "create_collection",
        {"vectors": {"vec": {"size": 4, "distance": "Cosine"}},
         "sparse_vectors": {"vec": {}}},
        path_params={"name": COLL})
    print(f"shared name -> {s} {raw[:300]}")
    v = rt.expect_rejected(s, raw, setup_ok=True)
    if v == "DEFECT_FOUND":
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print("dense/sparse shared vector name accepted (contract: disjoint names)")
        sys.exit(1)
    print(f"VERDICT: {v}")
    sys.exit(0 if v == "NO_DEFECT" else 2)
finally:
    cleanup(COLL)
