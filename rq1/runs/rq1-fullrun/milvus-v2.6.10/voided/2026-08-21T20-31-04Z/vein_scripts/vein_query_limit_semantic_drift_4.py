"""
vein_query_limit_semantic_drift: entities/query silently ignores invalid limit
values: limit=0 and limit=-5 both return ALL rows (code:0) instead of erroring,
while entities/search with the same values errors 65535 "topk [0] is invalid".
Also offset=-5 silently treated as 0 on query while search rejects offset=-1.
Cross-endpoint semantic drift within the same v2 surface.
Source: handler_v2.go query path vs search topk validation (proxy).
"""
import os, time
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL", "http://localhost:19530").rstrip("/")
HEADERS = {"Authorization": "Bearer root:Milvus", "Content-Type": "application/json"}
COLL = "vein_qd_4"
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


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + " " + str(detail)[:160])


safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COLL})
time.sleep(1)
safe_request("POST", "/v2/vectordb/collections/create", {
    "collectionName": COLL,
    "schema": {"enableDynamicField": False, "fields": [
        {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
        {"fieldName": "vec", "dataType": "FloatVector", "elementTypeParams": {"dim": 4}},
    ]},
    "indexParams": [{"fieldName": "vec", "indexName": "vi", "metricType": "L2",
                     "params": {"index_type": "HNSW", "M": 8, "efConstruction": 64}}],
})
time.sleep(3)
safe_request("POST", "/v2/vectordb/collections/load", {"collectionName": COLL})
time.sleep(2)
safe_request("POST", "/v2/vectordb/entities/insert", {
    "collectionName": COLL,
    "data": [{"id": i, "vec": [float(i), 1.0, 0.0, 0.0]} for i in range(10)]})
time.sleep(2)

# control: search limit=0 rejected
st, body, _ = safe_request("POST", "/v2/vectordb/entities/search",
                           {"collectionName": COLL, "data": [[0, 1, 0, 0]], "limit": 0})
check("control_search_limit0_rejected", isinstance(body, dict) and body.get("code") == 65535, body)

# attack: query limit=0 returns ALL
st, body, _ = safe_request("POST", "/v2/vectordb/entities/query",
                           {"collectionName": COLL, "filter": "id >= 0", "limit": 0})
check("query_limit0_returns_all", isinstance(body, dict) and body.get("code") == 0
      and len(body.get("data", [])) == 10, len(body.get("data", []) if isinstance(body, dict) else []))

# attack: query limit=-5 returns ALL
st, body, _ = safe_request("POST", "/v2/vectordb/entities/query",
                           {"collectionName": COLL, "filter": "id >= 0", "limit": -5})
check("query_limit_neg_returns_all", isinstance(body, dict) and body.get("code") == 0
      and len(body.get("data", [])) == 10, len(body.get("data", []) if isinstance(body, dict) else []))

# attack: query offset=-5 treated as 0
st, body, _ = safe_request("POST", "/v2/vectordb/entities/query",
                           {"collectionName": COLL, "filter": "id >= 0", "offset": -5, "limit": 3})
check("query_offset_neg_ignored", isinstance(body, dict) and body.get("code") == 0
      and [d.get("id") for d in body.get("data", [])] == [0, 1, 2], body)

try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COLL})
except Exception:
    pass

drift = any(p == "query_limit0_returns_all" for p in PASS) and any(p == "control_search_limit0_rejected" for p in PASS)
print(f"\nVERDICT: {'DEFECT_FOUND' if drift else 'NO_DEFECT'} "
      f"({len(PASS)} pass / {len(FAIL)} fail) — query vs search limit/offset validation drift (Type3 semantic)")
