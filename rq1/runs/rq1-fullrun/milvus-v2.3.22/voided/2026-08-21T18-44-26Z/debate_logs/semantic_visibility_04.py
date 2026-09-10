# Attack: insert->search->delete->search visibility + rowCount consistency
# contracts: milvus_inv_created_queryable / milvus_inv_count_consistency / milvus_behavioral_search_002
# source: https://github.com/milvus-io/milvus/blob/v2.3.22/internal/distributed/proxy/httpserver/handler_v2.go doc_version v2.3.22
import os, sys, time, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set"); sys.exit(2)
H = {"Content-Type": "application/json", "Authorization": "Bearer root:Milvus"}
DIM = 4
COL = "testvdb_sem_visibility_04"

def safe_request(method, endpoint, json=None, timeout=20):
    try:
        r = requests.request(method, f"{BASE_URL}{endpoint}", json=json, headers=H, timeout=timeout)
        try: body = r.json()
        except Exception: body = r.text
        return r.status_code, body, r.text
    except Exception as e:
        return -1, str(e), str(e)

def drop(name):
    try: safe_request("POST", "/v2/vectordb/collections/drop", json={"collectionName": name})
    except Exception: pass

def ok(b): return isinstance(b, dict) and b.get("code") == 200

drop(COL)
schema = {"fields": [
    {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
    {"fieldName": "color", "dataType": "VarChar", "elementTypeParams": {"max_length": 32}},
    {"fieldName": "vector", "dataType": "FloatVector", "elementTypeParams": {"dim": DIM}},
]}
s, b, r = safe_request("POST", "/v2/vectordb/collections/create",
    json={"collectionName": COL, "schema": schema, "indexParams": [
        {"fieldName": "vector", "indexName": "idx", "metricType": "L2", "params": {"index_type": "FLAT"}}]})
print("create:", s, r[:300])
if not (s == 200 and ok(b)):
    print("VERDICT: SCRIPT_ERROR - create failed"); sys.exit(2)
safe_request("POST", "/v2/vectordb/collections/load", json={"collectionName": COL})
time.sleep(2)

data = [
    {"id": 1, "color": "red",  "vector": [1.0, 0.0, 0.0, 0.0]},
    {"id": 2, "color": "blue", "vector": [0.9, 0.1, 0.0, 0.0]},
    {"id": 3, "color": "red",  "vector": [0.0, 5.0, 0.0, 0.0]},
]
s, b, r = safe_request("POST", "/v2/vectordb/entities/insert", json={"collectionName": COL, "data": data})
print("insert:", s, r[:200])
time.sleep(3)

defects = []
# 1. rowCount == 3
s, b, r = safe_request("POST", "/v2/vectordb/collections/get_stats", json={"collectionName": COL})
print("get_stats:", s, r[:200])
rc = ((b.get("data") or {}).get("rowCount") if ok(b) else None)
if rc != 3:
    defects.append(f"rowCount {rc} != 3 inserted (Type4_StateLogicViolation)")

# 2. search sees all 3
s, b, r = safe_request("POST", "/v2/vectordb/entities/search",
    json={"collectionName": COL, "data": [[1.0, 0.0, 0.0, 0.0]], "limit": 10, "outputFields": ["id"]})
print("search1:", s, r[:300])
hits = b.get("data") or [] if ok(b) else []
if len(hits) != 3:
    defects.append(f"search after insert found {len(hits)}/3 (Type4)")

# 3. delete id=1 -> search no longer returns it
# 3a. contract lists id as optional param for entities/delete; try id form first
s, b, r = safe_request("POST", "/v2/vectordb/entities/delete", json={"collectionName": COL, "id": 1})
print("delete_by_id:", s, r[:300])
code = b.get("code") if isinstance(b, dict) else None
if s == 200 and code != 200:
    defects.append(f"entities/delete by id rejected (code {code}, msg {str(b.get('message'))[:120]!r}) though contract lists id as supported param (BS-05 Documentation Drift / Type2)")
# 3b. delete via filter form
s, b, r = safe_request("POST", "/v2/vectordb/entities/delete", json={"collectionName": COL, "filter": "id == 1"})
print("delete_by_filter:", s, r[:200])
time.sleep(3)
s, b, r = safe_request("POST", "/v2/vectordb/entities/search",
    json={"collectionName": COL, "data": [[1.0, 0.0, 0.0, 0.0]], "limit": 10, "outputFields": ["id"]})
print("search2:", s, r[:300])
hits = b.get("data") or [] if ok(b) else []
ids = [str(h.get("id")) for h in hits]
if "1" in ids:
    defects.append(f"deleted id=1 still returned by search: {ids} (Type4_StateLogicViolation)")
if len(hits) != 2:
    defects.append(f"expected 2 hits after delete, got {len(hits)} (Type4)")

# 4. get_stats reflects deletion
s, b, r = safe_request("POST", "/v2/vectordb/collections/get_stats", json={"collectionName": COL})
rc2 = ((b.get("data") or {}).get("rowCount") if ok(b) else None)
print("get_stats2:", s, r[:200])
if rc2 is not None and rc not in (None, 3):
    pass  # rowCount correctness already checked
if rc2 is not None and rc2 not in (2, 3):
    defects.append(f"rowCount after delete = {rc2}, expected 2 (Type4)")

drop(COL)
if defects:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
    for d in defects: print("-", d)
    sys.exit(1)
print("VERDICT: NO_DEFECT")
