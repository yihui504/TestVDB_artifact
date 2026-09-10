"""
vein_unknown_field_silent_accept: with enableDynamicField=true, filter expressions
referencing a completely unknown field are silently accepted (code:0) and return
zero results, instead of erroring "field X not exist" as on dynamic-disabled
collections. Root cause: pkg/util/typeutil/schema.go:468 GetFieldFromNameDefaultJSON
falls back to the dynamic JSON field; unmatched JSON path evaluates to no-match.
Vectors: query/search/delete all affected (delete silently deletes 0).
"""
import os, json, time
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL", "http://localhost:19530").rstrip("/")
HEADERS = {"Authorization": "Bearer root:Milvus", "Content-Type": "application/json"}
COLL = "vein_ufs_1"
COLL_NODYN = "vein_ufs_1n"
PASS, FAIL = [], []


def safe_request(method, endpoint, json_body=None, timeout=10):
    try:
        r = requests.request(method, f"{BASE_URL}{endpoint}", json=json_body, headers=HEADERS, timeout=timeout)
        try:
            return r.status_code, r.json(), r.text
        except Exception:
            return r.status_code, r.text, r.text
    except Exception as e:
        return -1, str(e), str(e)


def create(coll, dynamic):
    schema_fields = [
        {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
        {"fieldName": "vec", "dataType": "FloatVector", "elementTypeParams": {"dim": 4}},
        {"fieldName": "val", "dataType": "Int64"},
    ]
    return safe_request("POST", "/v2/vectordb/collections/create", {
        "collectionName": coll,
        "schema": {"enableDynamicField": dynamic, "fields": schema_fields},
        "indexParams": [{"fieldName": "vec", "indexName": "vi", "metricType": "L2",
                         "params": {"index_type": "HNSW", "M": 8, "efConstruction": 64}}],
    })


def insert(coll, n):
    rows = [{"id": i, "vec": [float(i), 1.0, 0.0, 0.0], "val": i} for i in range(n)]
    return safe_request("POST", "/v2/vectordb/entities/insert", {"collectionName": coll, "data": rows})


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(f"{name} {detail}")
    print(("PASS " if cond else "FAIL ") + name + " " + str(detail)[:200])


# --- setup ---
for c, dyn in ((COLL, True), (COLL_NODYN, False)):
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": c})
    time.sleep(1)
    create(c, dyn)
    time.sleep(3)
    safe_request("POST", "/v2/vectordb/collections/load", {"collectionName": c})
    time.sleep(2)
    insert(c, 10)
time.sleep(2)

# --- control: same expression on dynamic-disabled collection must error 1100 ---
st, body, _ = safe_request("POST", "/v2/vectordb/entities/query",
                           {"collectionName": COLL_NODYN, "filter": "no_such_field_xyz > 5", "limit": 10})
check("control_nodyn_rejects", st == 200 and isinstance(body, dict) and body.get("code") == 1100, body)

# --- attack: identical expression on dynamic-enabled collection ---
st, body, _ = safe_request("POST", "/v2/vectordb/entities/query",
                           {"collectionName": COLL, "filter": "no_such_field_xyz > 5", "limit": 10})
check("dyn_query_silent_code0", st == 200 and isinstance(body, dict) and body.get("code") == 0
      and body.get("data", []) == [], body)
check("verdict", not (isinstance(body, dict) and body.get("code") == 0) or body.get("data", []) == [],
      "empty result on unknown field with dynamic schema = silent data hiding (typo immune)")

# search filter variant
st, body, _ = safe_request("POST", "/v2/vectordb/entities/search",
                           {"collectionName": COLL, "data": [[0, 1, 0, 0]], "limit": 3, "filter": "no_such_field_xyz > 5"})
check("dyn_search_silent_code0", st == 200 and isinstance(body, dict) and body.get("code") == 0, body)

# delete variant: silently deletes 0 rows, reports success
st, body, _ = safe_request("POST", "/v2/vectordb/entities/delete",
                           {"collectionName": COLL, "filter": "no_such_field_xyz > 5"})
check("dyn_delete_silent_code0", st == 200 and isinstance(body, dict) and body.get("code") == 0
      and body.get("data", {}).get("deleteCount") == 0, body)

# --- cleanup ---
for c in (COLL, COLL_NODYN):
    try:
        safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": c})
    except Exception:
        pass

print(f"\nVERDICT: {'DEFECT_FOUND' if any('dyn_query_silent_code0' in p for p in PASS) else 'NO_DEFECT'} "
      f"({len(PASS)} pass / {len(FAIL)} fail)")
