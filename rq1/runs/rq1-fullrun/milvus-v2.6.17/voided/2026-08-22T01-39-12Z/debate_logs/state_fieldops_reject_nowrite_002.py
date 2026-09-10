# state: fieldOps validation failure must leave collection untouched (milvus_inv_upsert_fieldops_reject_nowrite_001)
# Attack: strategy 1 (state consistency) x milvus_state_entities_upsert_fieldops_001
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import (safe_request, code_of, create_collection, load_collection,
                  drop_collection, query_all, unwrap_array_field)

CLS = "st_fo_reject_002"
verdict, detail = "NO_DEFECT", ""
try:
    drop_collection(CLS)
    create_collection(CLS)
    load_collection(CLS)
    print("insert:", safe_request("POST", "entities+insert", {"collectionName": CLS, "data": [
        {"id": 1, "vector": [0.1] * 8, "tags": ["orig"]} ]})[2])

    # malformed fieldOps: op on primary-key field (must be 1100, no write)
    s, b, raw = safe_request("POST", "entities+upsert", {
        "collectionName": CLS,
        "data": [{"id": 1, "vector": [0.2] * 8, "tags": ["x"]}],
        "fieldOps": [{"fieldName": "id", "op": "ARRAY_APPEND"}]})
    print("pk-op upsert:", s, raw)
    c = code_of(b)
    time.sleep(1)
    s2, b2, raw2 = query_all(CLS, output_fields=["tags", "vector"])
    print("post-reject query:", raw2)
    rows = (b2 or {}).get("data") or []
    if not rows:
        verdict, detail = "SCRIPT_ERROR", "query returned no rows"
    else:
        r = rows[0]
        tags = unwrap_array_field(r.get("tags"))
        if c == 0:
            print("NOTE: pk-fieldOp accepted (code 0) — violates 1100 PreExecute contract")
            verdict = "DEFECT_FOUND"
            detail = "fieldOps on primary key accepted"
        elif tags != ["orig"] or r.get("vector") != [0.1] * 8:
            verdict = "DEFECT_FOUND"
            detail = "rejected upsert (code %s) mutated state: tags=%s vec=%s" % (c, tags, r.get("vector"))
except Exception as e:
    verdict, detail = "SCRIPT_ERROR", str(e)
finally:
    drop_collection(CLS)
print(detail)
print("VERDICT: %s" % verdict)
