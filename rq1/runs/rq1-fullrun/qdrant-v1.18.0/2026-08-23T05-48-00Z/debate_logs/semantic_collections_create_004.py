# script_id: semantic_collections_create_004
# strategy: diagnosis_quality
# endpoint: collections+create
# Attack: qdrant_type_collections_create_003 (error message quality when invalid vectors config rejected)
# constraint_ids: qdrant_type_collections_create_003
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-02 error message negligence
"""Diagnosis quality (Type-2): invalid distance enum must be rejected 400
with an error naming 'distance' and hinting valid values. Rubric:
param_named(1) + format_hint(1) + actionable(1); score < 2 = defect."""
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

COLL = f"sem_cc_diag_{TS}"
try:
    s, raw = rt.request("PUT", "create_collection",
        {"vectors": {"size": 4, "distance": "Bogus"}},
        path_params={"name": COLL})
    print(f"status={s} raw={raw}")
    # must be rejected first (per inferred constraint 003)
    v = rt.expect_rejected(s, raw, setup_ok=True)
    if v != "NO_DEFECT":
        print(f"VERDICT: {v}")
        sys.exit(2 if v == "SCRIPT_ERROR" else 1)
    # Type-2 rubric: param named / format hint / actionable
    low = raw.lower()
    score = 0
    if "distance" in low:
        score += 1
    if any(h in low for h in ["must be", "expected", "should be", "valid",
                              "variant", "enum", "cosine", "euclid", "dot", "manhattan"]):
        score += 1
    if any(h in low for h in ["correct", "try", "use", "change", "specify",
                              "provide", "did not match"]):
        score += 1
    print(f"diagnosis score: {score}/3")
    if score < 2:
        print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics)")
        print(f"Invalid distance enum error lacks param name/format guidance (score {score}/3)")
        sys.exit(1)
    print("VERDICT: NO_DEFECT")
    sys.exit(0)
finally:
    cleanup(COLL)
