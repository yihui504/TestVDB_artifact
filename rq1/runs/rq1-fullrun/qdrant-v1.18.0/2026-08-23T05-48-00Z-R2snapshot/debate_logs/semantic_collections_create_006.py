# script_id: semantic_collections_create_006
# strategy: behavioral_contract
# endpoint: collections+create
# Attack: qdrant_type_collections_create_005 (scalar quantization type=int8 only + quantile [0.5,1.0] boundaries both directions)
# constraint_ids: qdrant_type_collections_create_005
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-05 semantic contract
"""Scalar quantization semantics: type must be int8 only (int16 rejected),
quantile range [0.5, 1.0] inclusive at both bounds, out-of-range rejected."""
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

cases = [
    ("int8", 0.5, True),   # legal lower bound
    ("int8", 1.0, True),   # legal upper bound
    ("int8", 0.4, False),  # below range
    ("int8", 1.1, False),  # above range
    ("int16", 0.9, False), # illegal type
]
for i, (typ, q, legal) in enumerate(cases):
    COLL = f"sem_cc_sq_{i}_{TS}"
    try:
        s, raw = rt.request("PUT", "create_collection",
            {"vectors": {"size": 4, "distance": "Cosine"},
             "quantization_config": {"scalar": {"type": typ, "quantile": q}}},
            path_params={"name": COLL})
        print(f"scalar type={typ!r} quantile={q} -> {s} {raw[:200]}")
        v = rt.judge_200(s, raw, setup_ok=True) if legal else rt.expect_rejected(s, raw, setup_ok=True)
        if v != "NO_DEFECT":
            print(f"VERDICT: {v}")
            if v == "DEFECT_FOUND":
                print(f"scalar config (type={typ!r}, quantile={q}) expected {'accept' if legal else 'reject'}")
            sys.exit(2 if v == "SCRIPT_ERROR" else 1)
    finally:
        cleanup(COLL)

print("VERDICT: NO_DEFECT")
sys.exit(0)
