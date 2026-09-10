# script_id: semantic_collections_create_002
# strategy: behavioral_contract
# endpoint: collections+create
# Attack: qdrant_type_collections_create_001 (enum exactness: synonyms/case variants must be rejected, no fuzzy coercion)
# constraint_ids: qdrant_type_collections_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-01 type coercion trust
"""Type confusion (semantic): distance enum must be exact. Case variants and
aliases like 'Euclidean' (threat model note: 'Euclid' is the official enum
name) must be rejected with 400, never silently coerced."""
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

defect = None
for i, bogus in enumerate(["Cosine ", "cosine", "Euclidean", "COSINE"]):
    COLL = f"sem_cc_enum2_{i}_{TS}"
    try:
        s, raw = rt.request("PUT", "create_collection",
            {"vectors": {"size": 4, "distance": bogus}},
            path_params={"name": COLL})
        print(f"distance={bogus!r} -> {s} {raw[:200]}")
        v = rt.expect_rejected(s, raw, setup_ok=True)
        if v == "DEFECT_FOUND":
            defect = f"enum synonym {bogus!r} accepted (contract: exact enum only)"
            break
        if v == "SCRIPT_ERROR":
            print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
    finally:
        cleanup(COLL)

if defect:
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)")
    print(defect)
    sys.exit(1)
print("VERDICT: NO_DEFECT")
sys.exit(0)
