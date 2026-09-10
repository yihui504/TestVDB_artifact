# script_id: semantic_collections_create_003
# strategy: type_coercion
# endpoint: collections+create
# Attack: qdrant_type_collections_create_002 (vectors.size uint64: string/float/bool/null must be rejected)
# constraint_ids: qdrant_type_collections_create_002
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-01 parameter type coercion trust
"""Implicit type coercion: contract says vectors.size IS uint64 integer.
Send "4" (string), 4.0 (float), true (bool), null — all must be rejected;
silently coerced acceptance is a defect."""
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
for i, size in enumerate(["4", 4.0, True, None]):
    COLL = f"sem_cc_size_{i}_{TS}"
    try:
        s, raw = rt.request("PUT", "create_collection",
            {"vectors": {"size": size, "distance": "Cosine"}},
            path_params={"name": COLL})
        print(f"size={size!r} -> {s} {raw[:200]}")
        v = rt.expect_rejected(s, raw, setup_ok=True)
        if v == "DEFECT_FOUND":
            defect = f"non-uint64 size {size!r} accepted"
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
