# Attack: COSINE distance domain [0,2] and radius direction on COSINE collection
# Blindspot BS-05; contract milvus_bc_v1_vs_v2_semantics (v2 quick-create default COSINE)
# source: https://github.com/milvus-io/milvus/blob/v2.3.22/pkg/util/metric/metric_type.go doc_version v2.3.22
import os, sys, time, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set"); sys.exit(2)
H = {"Content-Type": "application/json", "Authorization": "Bearer root:Milvus"}
DIM = 4
COL = "testvdb_sem_cosine_03"

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

drop(COL)
# explicit-schema COSINE, autoID=false so we control ids
schema = {"fields": [
    {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
    {"fieldName": "vector", "dataType": "FloatVector", "elementTypeParams": {"dim": DIM}},
]}
s, b, r = safe_request("POST", "/v2/vectordb/collections/create",
    json={"collectionName": COL, "schema": schema, "indexParams": [
        {"fieldName": "vector", "indexName": "idx", "metricType": "COSINE",
         "params": {"index_type": "FLAT"}}]})
print("create:", s, r[:300])
if not (s == 200 and isinstance(b, dict) and b.get("code") == 200):
    print("VERDICT: SCRIPT_ERROR - create failed"); sys.exit(2)
safe_request("POST", "/v2/vectordb/collections/load", json={"collectionName": COL})
time.sleep(2)

# v0=[1,0,0,0]; v1 identical; v2 90deg [0,1,0,0]; v3 opposite [-1,0,0,0]
s, b, r = safe_request("POST", "/v2/vectordb/entities/insert", json={"collectionName": COL, "data": [
    {"id": 1, "vector": [1, 0, 0, 0]},
    {"id": 2, "vector": [0, 1, 0, 0]},
    {"id": 3, "vector": [-1, 0, 0, 0]},
]})
print("insert:", s, r[:200])
time.sleep(2)

defects = []
Q = [[1.0, 0.0, 0.0, 0.0]]
s, b, r = safe_request("POST", "/v2/vectordb/entities/search",
    json={"collectionName": COL, "data": Q, "limit": 3, "outputFields": ["id"]})
print("cosine_search:", s, r[:400])
if s == 200 and isinstance(b, dict) and b.get("code") == 200:
    hits = b.get("data") or []
    dists = [h.get("distance") for h in hits]
    ids = [h.get("id") for h in hits]
    if len(hits) != 3:
        defects.append(f"expected 3 hits, got {len(hits)} (Type4)")
    # COSINE similarity -> distance = 1 - sim, domain [0, 2]; identical -> 0, opposite -> 2
    d_same = dists[0] if ids[0] in (1, "1") else None
    for d in dists:
        if d is not None and (d < -1e-6 or d > 2.0 + 1e-6):
            defects.append(f"COSINE distance {d} outside [0,2] domain (Type4_StateLogicViolation)")
    if ids and str(ids[0]) not in ("1",) :
        defects.append(f"nearest should be id=1 (identical vector), got {ids} (Type4)")
    if len(dists) == 3 and dists[-1] is not None and abs(dists[-1] - 2.0) > 0.05 and str(ids[-1]) == "3":
        defects.append(f"opposite vector distance {dists[-1]}, expected ~2.0 (Type4)")
    print("ids:", ids, "dists:", dists)

drop(COL)
if defects:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
    for d in defects: print("-", d)
    sys.exit(1)
print("VERDICT: NO_DEFECT")
