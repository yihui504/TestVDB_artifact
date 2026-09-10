# script_id: semantic_collections_create_001
# strategy: behavioral_contract
# endpoint: collections+create
# Attack: qdrant_type_collections_create_001 (distance enum roundtrip: create Cosine -> describe must read back Cosine)
# constraint_ids: qdrant_type_collections_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-05 semantic contract
"""Behavioral contract: vectors.distance enum {Cosine, Euclid, Dot, Manhattan}.
Create with Cosine then describe-collection must read back exactly Cosine
(config persistence contract)."""
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

COLL = f"sem_cc_enum_1_{TS}"
try:
    ok, err = rt.setup_default(COLL, dim=4)
    if not ok:
        print(f"VERDICT: SCRIPT_ERROR — setup: {err}"); sys.exit(2)
    # attack: describe readback must report the exact enum value persisted
    s, raw = rt.request("GET", "describe_collection", path_params={"name": COLL})
    print(f"describe: {s} {raw[:400]}")
    v = rt.judge_200(s, raw, setup_ok=True)
    if v == "NO_DEFECT":
        try:
            conf = json.loads(raw).get("result", {}).get("config", {}).get("params", {}).get("vectors", {})
            dist = conf.get("distance") if isinstance(conf, dict) else None
            if dist != "Cosine":
                print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
                print(f"describe readback distance={dist!r} != requested Cosine")
                sys.exit(1)
        except Exception as e:
            print(f"parse note: {e}")
    print(f"VERDICT: {v}")
    sys.exit(0 if v == "NO_DEFECT" else (1 if v == "DEFECT_FOUND" else 2))
finally:
    cleanup(COLL)
