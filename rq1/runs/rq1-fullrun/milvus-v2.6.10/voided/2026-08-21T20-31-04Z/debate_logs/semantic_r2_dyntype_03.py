# semantic_r2_dyntype_03 — dynamic field type-mixing retrieval semantics
# Attack: entities+insert dynamic field with mixed types across rows -> entities+query filter on that field
#   x strategy: filter_semantics + behavioral_contract (R2 type_constraint: dynamic field type consistency)
import os, sys, time, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set"); sys.exit(2)
AUTH = {"Content-Type": "application/json",
        "Authorization": "Bearer " + os.environ.get("TESTVDB_MILVUS_TOKEN", "root:Milvus")}

def safe_request(method, endpoint, json_body=None, timeout=15):
    try:
        r = requests.request(method, BASE_URL + endpoint, json=json_body, headers=AUTH, timeout=timeout)
        try:
            body = r.json()
        except Exception:
            body = r.text
        return r.status_code, body, r.text
    except Exception as e:
        return -1, str(e), str(e)

COL = "sem_r2_dyntype"
try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass
st, body, raw = safe_request("POST", "/v2/vectordb/collections/create",
                             {"collectionName": COL, "dimension": 4})
print("create:", st, raw[:120])
if not (st == 200 and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — create failed: %s" % raw[:200]); sys.exit(2)

# same dynamic field name, different JSON types per row
rows = [
    {"id": 1, "vector": [0.1] * 4, "mix_val": 100},
    {"id": 2, "vector": [0.2] * 4, "mix_val": "100"},
    {"id": 3, "vector": [0.3] * 4, "mix_val": 55},
]
st, body, raw = safe_request("POST", "/v2/vectordb/entities/insert",
                             {"collectionName": COL, "data": rows})
print("insert mixed types:", st, raw[:250])
if not (st == 200 and body.get("code") == 0):
    # rejecting at insert is defensible enforcement — check error names the field
    msg = raw.lower()
    if "mix_val" not in msg:
        print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — mixed-type dynamic insert rejected without naming field: %s" % raw[:200])
        sys.exit(1)
    print("NOTE: insert rejected mixed types with named error — consistent enforcement, no defect path for retrieval")
    try:
        safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
    except Exception:
        pass
    print("VERDICT: NO_DEFECT")
    sys.exit(0)

# insert accepted mixed types: numeric filter must match ONLY the numeric row(s), never the string
st, body, raw = safe_request("POST", "/v2/vectordb/entities/query", {
    "collectionName": COL, "filter": "mix_val > 60", "outputFields": ["id", "mix_val"], "limit": 10})
print("query mix_val > 60:", st, raw[:350])
if not (st == 200 and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — query failed: %s" % raw[:200]); sys.exit(2)
ids = sorted(r.get("id") for r in body.get("data", []))
if 2 in ids:
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess/Type4) — string \"100\" matched numeric filter mix_val > 60 (implicit cross-type coercion)")
    sys.exit(1)
if 1 not in ids or 3 in ids:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — mix_val > 60 should match exactly id 1, got %s" % ids)
    sys.exit(1)

# string equality filter must match only the string row
st, body, raw = safe_request("POST", "/v2/vectordb/entities/query", {
    "collectionName": COL, "filter": "mix_val == \"100\"", "outputFields": ["id"], "limit": 10})
print("query mix_val == \"100\":", st, raw[:350])
if st == 200 and body.get("code") == 0:
    ids = sorted(r.get("id") for r in body.get("data", []))
    if ids != [2]:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — string equality on mixed field: expected [2], got %s" % ids)
        sys.exit(1)

try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass
print("VERDICT: NO_DEFECT")
