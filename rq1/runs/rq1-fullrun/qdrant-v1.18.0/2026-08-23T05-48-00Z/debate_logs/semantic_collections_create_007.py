# script_id: semantic_collections_create_007
# strategy: behavioral_contract
# endpoint: collections+create
# Attack: qdrant_type_collections_create_006 (binary quantization encoding enum one_bit|two_bits|one_and_half_bits; int 1 as type-confusion probe)
# constraint_ids: qdrant_type_collections_create_006
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-01 type coercion trust
"""Binary quantization enum semantics: the three legal encodings accepted;
'three_bits' and integer 1 (type confusion) must be rejected."""
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

for i, enc in enumerate(["one_bit", "two_bits", "one_and_half_bits", "three_bits", 1]):
    COLL = f"sem_cc_bq_{i}_{TS}"
    try:
        s, raw = rt.request("PUT", "create_collection",
            {"vectors": {"size": 4, "distance": "Cosine"},
             "quantization_config": {"binary": {"encoding": enc}}},
            path_params={"name": COLL})
        print(f"encoding={enc!r} -> {s} {raw[:200]}")
        legal = enc in ("one_bit", "two_bits", "one_and_half_bits")
        v = rt.judge_200(s, raw, setup_ok=True) if legal else rt.expect_rejected(s, raw, setup_ok=True)
        if v != "NO_DEFECT":
            print(f"VERDICT: {v}")
            if v == "DEFECT_FOUND":
                print(f"encoding={enc!r}: expected {'accept' if legal else 'reject'}")
            sys.exit(2 if v == "SCRIPT_ERROR" else 1)
    finally:
        cleanup(COLL)

print("VERDICT: NO_DEFECT")
sys.exit(0)
