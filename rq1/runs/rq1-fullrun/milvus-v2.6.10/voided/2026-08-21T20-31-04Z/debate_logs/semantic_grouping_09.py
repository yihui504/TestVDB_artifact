# semantic_grouping_09 — groupingField/groupSize/strictGroupSize semantics
# Attack: entities+search params groupingField/groupSize × strategy filter_semantics/search_correctness
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

COL = "sem_group_09"
try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass

# full schema: pk + group field + vector
st, body, raw = safe_request("POST", "/v2/vectordb/collections/create", {
    "collectionName": COL,
    "schema": {
        "autoId": False,
        "fields": [
            {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
            {"fieldName": "grp", "dataType": "VarChar", "isPartitionKey": False, "elementType": "VarChar"},
            {"fieldName": "vector", "dataType": "FloatVector", "dimension": 4},
        ]}})
if not (st == 200 and isinstance(body, dict) and body.get("code") == 0):
    # fallback quick mode (dynamic field) — VarChar needs max_length in some builds
    st, body, raw = safe_request("POST", "/v2/vectordb/collections/create", {
        "collectionName": COL, "dimension": 4, "metricType": "L2",
        "primaryFieldName": "id", "vectorFieldName": "vector",
        "schema": {
            "autoId": False,
            "enableDynamicField": True,
            "fields": [
                {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
                {"fieldName": "vector", "dataType": "FloatVector", "dimension": 4},
            ]}})
print("create:", st, raw[:250])
if not (st == 200 and isinstance(body, dict) and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — create failed both modes"); sys.exit(2)

safe_request("POST", "/v2/vectordb/indexes/create", {
    "collectionName": COL,
    "indexParams": [{"fieldName": "vector", "indexName": "v", "metricType": "L2",
                     "indexType": "FLAT"}]})
safe_request("POST", "/v2/vectordb/collections/load", {"collectionName": COL})
time.sleep(2)

# 6 entities: 3 groups ("red" x3 near, "blue" x2, "green" x1); query = origin
rows = [
    {"id": 1, "vector": [0.1] * 4, "grp": "red"},
    {"id": 2, "vector": [0.2] * 4, "grp": "red"},
    {"id": 3, "vector": [0.3] * 4, "grp": "red"},
    {"id": 4, "vector": [0.4] * 4, "grp": "blue"},
    {"id": 5, "vector": [0.5] * 4, "grp": "blue"},
    {"id": 6, "vector": [0.6] * 4, "grp": "green"},
]
st, body, raw = safe_request("POST", "/v2/vectordb/entities/insert",
                             {"collectionName": COL, "data": rows})
print("insert:", st, raw[:150])
if not (st == 200 and isinstance(body, dict) and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — insert failed"); sys.exit(2)
time.sleep(1)

def grouped(grouping_field, group_size=1, strict=False, limit=10):
    p = {"collectionName": COL, "data": [[0.0] * 4], "limit": limit,
         "groupingField": grouping_field, "outputFields": ["grp"]}
    if group_size != 1:
        p["groupSize"] = group_size
    if strict:
        p["strictGroupSize"] = True
    st, body, raw = safe_request("POST", "/v2/vectordb/entities/search", p)
    code = body.get("code") if isinstance(body, dict) else None
    data = (body.get("data") or []) if isinstance(body, dict) else []
    return st, code, data, raw

# baseline groupSize=1: one row per group -> at most 3 distinct groups
st, code, data, raw = grouped("grp")
print("groupSize=1:", st, raw[:300])
if code != 0:
    print("VERDICT: SCRIPT_ERROR — groupingField search failed: %s" % raw[:250]); sys.exit(2)
grps = [r.get("grp") for r in data]
print("groups:", grps)
if len(grps) != len(set(grps)):
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — groupSize=1 returned duplicate groups: %r" % grps)
    sys.exit(1)

# groupSize=2, strict: red contributes 2 (it has >=2), total = 2+2+1 = 5
st, code, data, raw = grouped("grp", group_size=2, strict=True)
print("groupSize=2 strict:", st, raw[:300])
if code != 0:
    print("VERDICT: SCRIPT_ERROR — groupSize=2 search failed"); sys.exit(2)
from collections import Counter
cnt = Counter(r.get("grp") for r in data)
print("counts:", dict(cnt))
if cnt.get("red", 0) != 2:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — strict groupSize=2 but 'red' (3 members) returned %d" % cnt.get("red", 0))
    sys.exit(1)
if any(v > 2 for v in cnt.values()):
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — groupSize=2 exceeded: %r" % dict(cnt))
    sys.exit(1)

# unknown groupingField -> clear rejection naming the field
st, code, data, raw = grouped("no_such_field")
print("bad groupingField:", st, raw[:300])
if code == 0:
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — unknown groupingField accepted")
    sys.exit(1)
if "no_such_field" not in raw and "field" not in raw.lower():
    print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — groupingField error names neither field nor cause: %s" % raw[:250])
    sys.exit(1)

try:
    safe_request("POST", "/v2/vectordb/collections/release", {"collectionName": COL})
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass
print("VERDICT: NO_DEFECT")
