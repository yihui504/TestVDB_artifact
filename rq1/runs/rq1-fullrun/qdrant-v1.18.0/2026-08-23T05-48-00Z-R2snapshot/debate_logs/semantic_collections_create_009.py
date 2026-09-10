# script_id: semantic_collections_create_009
# strategy: behavioral_contract
# endpoint: collections+create
# Attack: qdrant_type_collections_create_008 (sparse vector distance not user-settable, always Dot)
# constraint_ids: qdrant_type_collections_create_008
# source_url: https://qdrant.tech/documentation/concepts/vectors/
# doc_version: 1.18.x (versioned)
# Blindspot: BS-05 semantic contract
"""Inferred contract: sparse vector distance is always Dot and not settable.
Attempting to set sparse distance must be rejected; if accepted, readback
must still be Dot (checked here via describe after PATCH)."""
import os, sys, time, json
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

COLL = f"sem_cc_spsd_{TS}"
try:
    # create with sparse config carrying a user-set distance (should be rejected)
    s, raw = rt.request("PUT", "create_collection",
        {"sparse_vectors": {"sp": {"distance": "Euclid"}}},
        path_params={"name": COLL})
    print(f"create sparse w/ distance -> {s} {raw[:300]}")
    if s in (200, 201):
        # if accepted, readback distance must still be Dot (not user value)
        s2, raw2 = rt.request("GET", "describe_collection", path_params={"name": COLL})
        print(f"describe -> {s2} {raw2[:400]}")
        try:
            sv = json.loads(raw2).get("result", {}).get("config", {}).get("params", {}).get("sparse_vectors", {})
            dist = sv.get("sp", {}).get("distance") if isinstance(sv, dict) else None
            if dist not in (None, "Dot"):
                print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
                print(f"sparse distance user-settable: readback {dist!r} (contract: always Dot, not settable)")
                sys.exit(1)
        except Exception as e:
            print(f"parse note: {e}")
        print("VERDICT: NO_DEFECT")
        sys.exit(0)
    v = rt.expect_rejected(s, raw, setup_ok=True)
    if v == "DEFECT_FOUND":
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print("sparse distance user-settable (contract: always Dot, not settable)")
        sys.exit(1)
    print(f"VERDICT: {v}")
    sys.exit(0 if v == "NO_DEFECT" else 2)
finally:
    cleanup(COLL)
