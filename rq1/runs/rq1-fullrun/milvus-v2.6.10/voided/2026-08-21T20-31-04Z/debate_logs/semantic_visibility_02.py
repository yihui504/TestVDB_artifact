# semantic_visibility_02 — insert visibility under consistencyLevel Strong/Bounded/Eventually
# Attack: behavioral_contract milvus_bc_crud_visibility_001 + milvus_bc_delete_invisibility_001
#   × entities+search consistencyLevel enum
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

COL = "sem_vis_02"
try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass

st, body, raw = safe_request("POST", "/v2/vectordb/collections/create", {
    "collectionName": COL, "dimension": 8,
    "metricType": "L2"})
print("create:", st, raw[:200])
if not (st == 200 and isinstance(body, dict) and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — create failed"); sys.exit(2)

st, body, raw = safe_request("POST", "/v2/vectordb/indexes/create", {
    "collectionName": COL,
    "indexParams": [{"fieldName": "vector", "indexName": "vec_idx",
                     "metricType": "L2", "indexType": "FLAT"}]})
print("index:", st, raw[:200])

st, body, raw = safe_request("POST", "/v2/vectordb/collections/load", {"collectionName": COL})
print("load:", st, raw[:200])
if not (st == 200 and isinstance(body, dict) and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — load failed"); sys.exit(2)
time.sleep(2)

rows = [{"id": i, "vector": [0.01 * (i + 1)] * 8, "cat": "A" if i < 3 else "B"} for i in range(5)]
st, body, raw = safe_request("POST", "/v2/vectordb/entities/insert",
                             {"collectionName": COL, "data": rows})
print("insert:", st, raw[:200])
if not (st == 200 and isinstance(body, dict) and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — insert failed"); sys.exit(2)

# Strong read-your-writes: immediately searchable at Strong
for level in ("Strong", "Bounded"):
    st, body, raw = safe_request("POST", "/v2/vectordb/entities/search", {
        "collectionName": COL, "data": [[0.0] * 8], "limit": 10,
        "consistencyLevel": level,
        "filter": 'cat == "A"'})
    print("search %s:" % level, st, raw[:400])
    if not (st == 200 and isinstance(body, dict) and body.get("code") == 0):
        print("VERDICT: SCRIPT_ERROR — search %s failed: %s" % (level, raw[:200])); sys.exit(2)
    results = body.get("data") or []
    if level == "Strong" and len(results) != 3:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — Strong consistency right after insert returned %d results, expected 3 (read-your-writes violated)" % len(results))
        sys.exit(1)

# delete->invisibility at Strong
st, body, raw = safe_request("POST", "/v2/vectordb/entities/delete",
                             {"collectionName": COL, 'filter': 'cat == "A"'})
print("delete:", st, raw[:200])
if not (st == 200 and isinstance(body, dict) and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — delete failed"); sys.exit(2)

st, body, raw = safe_request("POST", "/v2/vectordb/entities/query", {
    "collectionName": COL, 'filter': 'cat == "A"',
    "outputFields": ["id", "cat"], "consistencyLevel": "Strong"})
print("query after delete:", st, raw[:400])
if not (st == 200 and isinstance(body, dict) and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — query failed"); sys.exit(2)
results = body.get("data") or []
if len(results) != 0:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — deleted entities still visible at Strong: %d rows returned" % len(results))
    sys.exit(1)

try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass
print("VERDICT: NO_DEFECT")
