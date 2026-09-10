# script_id: semantic_collections_create_011
# strategy: behavioral_contract
# endpoint: collections+create
# Attack: qdrant_type_collections_create_010 (per-name dimensionality consistency: wrong-dim upsert rejected) + qdrant_range_collections_create_001 (hnsw_config.m>=0 legal value roundtrip)
# constraint_ids: qdrant_type_collections_create_010, qdrant_range_collections_create_001
# source_url: https://qdrant.tech/documentation/concepts/collections/
# doc_version: 1.18.x (versioned)
# Blindspot: BS-05 semantic contract
"""Two contracts: (a) vectors within collection share size per name —
upserting a 3-dim vector into a 4-dim collection must be rejected;
(b) hnsw_config.m=16 (>=0) legal on create and describe must read back 16."""
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

COLL = f"sem_cc_consist_{TS}"
try:
    ok, err = rt.setup_default(COLL, dim=4)
    if not ok:
        print(f"VERDICT: SCRIPT_ERROR — setup: {err}"); sys.exit(2)
    # (a) wrong-dim upsert must be rejected (per-name size consistency)
    s, raw = rt.request("PUT", "upsert_points",
        {"points": [{"id": 1, "vector": [0.1, 0.2, 0.3]}]},
        path_params={"name": COLL})
    print(f"3-dim into 4-dim -> {s} {raw[:300]}")
    v1 = rt.expect_rejected(s, raw, setup_ok=True)
    if v1 != "NO_DEFECT":
        print(f"VERDICT: {v1}")
        if v1 == "DEFECT_FOUND":
            print("3-dim vector accepted into 4-dim collection (contract: consistent size per name)")
        sys.exit(2 if v1 == "SCRIPT_ERROR" else 1)

    # (b) hnsw_config.m legal roundtrip
    COLL2 = f"sem_cc_hnsw_{TS}"
    try:
        s2, raw2 = rt.request("PUT", "create_collection",
            {"vectors": {"size": 4, "distance": "Cosine"},
             "hnsw_config": {"m": 16, "ef_construct": 100}},
            path_params={"name": COLL2})
        print(f"hnsw m=16 create -> {s2} {raw2[:200]}")
        v2 = rt.judge_200(s2, raw2, setup_ok=True)
        if v2 != "NO_DEFECT":
            print(f"VERDICT: {v2}")
            sys.exit(2 if v2 == "SCRIPT_ERROR" else 1)
        s3, raw3 = rt.request("GET", "describe_collection", path_params={"name": COLL2})
        print(f"describe -> {s3} {raw3[:400]}")
        if s3 == 200:
            try:
                m = json.loads(raw3).get("result", {}).get("config", {}).get("hnsw_config", {}).get("m")
                if m != 16:
                    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
                    print(f"hnsw m readback {m!r} != 16")
                    sys.exit(1)
            except Exception as e:
                print(f"parse note: {e}")
    finally:
        cleanup(COLL2)
    print("VERDICT: NO_DEFECT")
    sys.exit(0)
finally:
    cleanup(COLL)
