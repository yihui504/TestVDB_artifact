# script_id: semantic_collections_create_008
# strategy: behavioral_contract
# endpoint: collections+create
# Attack: qdrant_type_collections_create_007 (datatype enum float32|uint8|float16|turbo4; turbo4 dense-only must be rejected for sparse)
# constraint_ids: qdrant_type_collections_create_007
# source_url: https://qdrant.tech/documentation/concepts/vectors/
# doc_version: 1.18.x (versioned)
# Blindspot: BS-05 semantic contract
"""Vector datatype enum semantics: dense datatypes accepted; turbo4 on
sparse_vectors must be rejected (dense-only per contract)."""
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

# dense: contract enum datatypes accepted, bogus rejected
for i, dt in enumerate(["float32", "uint8", "float16", "turbo4", "float64"]):
    COLL = f"sem_cc_dt_{i}_{TS}"
    try:
        s, raw = rt.request("PUT", "create_collection",
            {"vectors": {"size": 4, "distance": "Cosine", "datatype": dt}},
            path_params={"name": COLL})
        print(f"dense datatype={dt!r} -> {s} {raw[:200]}")
        legal = dt in ("float32", "uint8", "float16", "turbo4")
        v = rt.judge_200(s, raw, setup_ok=True) if legal else rt.expect_rejected(s, raw, setup_ok=True)
        if v != "NO_DEFECT":
            print(f"VERDICT: {v}")
            if v == "DEFECT_FOUND":
                print(f"dense datatype={dt!r}: expected {'accept' if legal else 'reject'}")
            sys.exit(2 if v == "SCRIPT_ERROR" else 1)
    finally:
        cleanup(COLL)

# turbo4 must NOT be allowed for sparse vectors (explicit contract)
COLL2 = f"sem_cc_turbo4_{TS}"
try:
    s, raw = rt.request("PUT", "create_collection",
        {"sparse_vectors": {"sparse_txt": {"datatype": "turbo4"}}},
        path_params={"name": COLL2})
    print(f"sparse turbo4 -> {s} {raw[:200]}")
    v = rt.expect_rejected(s, raw, setup_ok=True)
    if v == "DEFECT_FOUND":
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)")
        print("turbo4 accepted for sparse vectors (contract: dense-only)")
        sys.exit(1)
    print(f"VERDICT: {v}")
    sys.exit(0 if v == "NO_DEFECT" else 2)
finally:
    cleanup(COLL2)
