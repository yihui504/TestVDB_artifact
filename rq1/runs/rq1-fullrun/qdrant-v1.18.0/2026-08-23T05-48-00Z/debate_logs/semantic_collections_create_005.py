# script_id: semantic_collections_create_005
# strategy: behavioral_contract
# endpoint: collections+create
# Attack: qdrant_type_collections_create_004 (product quantization compression enum x4|x8|x16|x32|x64: legal accepted, illegal rejected)
# constraint_ids: qdrant_type_collections_create_004
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-05 semantic contract
"""Enum semantics both directions: legal compression ratios x4/x8 must be
accepted; x3/2x must be rejected 400. Judge helpers only cover rejection,
so the legal-acceptance branch is checked via printed status."""
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

for i, comp in enumerate(["x4", "x8", "x3", "2x"]):
    COLL = f"sem_cc_pq_{i}_{TS}"
    try:
        s, raw = rt.request("PUT", "create_collection",
            {"vectors": {"size": 4, "distance": "Cosine"},
             "quantization_config": {"product": {"compression": comp}}},
            path_params={"name": COLL})
        print(f"compression={comp!r} -> {s} {raw[:200]}")
        if comp in ("x4", "x8"):
            v = rt.judge_200(s, raw, setup_ok=True)
        else:
            v = rt.expect_rejected(s, raw, setup_ok=True)
        if v != "NO_DEFECT":
            print(f"VERDICT: {v}")
            if v == "DEFECT_FOUND":
                print(f"compression={comp!r}: expected {'accept' if comp in ('x4','x8') else 'reject'}")
            sys.exit(2 if v == "SCRIPT_ERROR" else 1)
    finally:
        cleanup(COLL)

print("VERDICT: NO_DEFECT")
sys.exit(0)
