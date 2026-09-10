# semantic_r2b_hybrid_rrf_02 — hybrid_search RRF rank math (R1 dropped test backfill, blind R2b)
# Attack: entities+hybrid_search rerank RRF — correct id ordering per hand-computed KRRF scores -> Type4
import os, sys, time, math, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set"); sys.exit(2)
AUTH = {"Content-Type": "application/json",
        "Authorization": "Bearer " + os.environ.get("TESTVDB_MILVUS_TOKEN", "root:Milvus")}

def safe_request(method, endpoint, json_body=None, timeout=20):
    try:
        r = requests.request(method, BASE_URL + endpoint, json=json_body, headers=AUTH, timeout=timeout)
        try:
            body = r.json()
        except Exception:
            body = r.text
        return r.status_code, body, r.text
    except Exception as e:
        return -1, str(e), str(e)

COL = "sem_r2b_rrf"
try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COL})
except Exception:
    pass

# full schema: two float vectors (dim 4) + Int64 pk; vector indexes auto with FLAT not needed (quick-set)
st, body, raw = safe_request("POST", "/v2/vectordb/collections/create", {
    "collectionName": COL,
    "schema": {
        "autoId": False,
        "fields": [
            {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
            {"fieldName": "va", "dataType": "FloatVector", "elementTypeParams": {"dim": "4"}},
            {"fieldName": "vb", "dataType": "FloatVector", "elementTypeParams": {"dim": "4"}},
        ],
    },
    "indexParams": [
        {"fieldName": "va", "indexName": "idx_va", "metricType": "L2",
         "indexType": "FLAT", "elementTypeParams": {}},
        {"fieldName": "vb", "indexName": "idx_vb", "metricType": "L2",
         "indexType": "FLAT", "elementTypeParams": {}},
    ],
})
print("create:", st, raw[:160])
if not (st == 200 and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — create failed: %s" % raw[:300]); sys.exit(2)

rows = [
    {"id": 101, "va": [0.0] * 4,   "vb": [1.0, 0, 0, 0]},   # rank1 in A, rank3 in B -> KRRF 1+1/5=1.2
    {"id": 102, "va": [0.5] * 4,   "vb": [0.0] * 4},        # rank3 in A, rank1 in B -> KRRF 1/5+1=1.2
    {"id": 103, "va": [0.1] * 4,   "vb": [0.1] * 4},        # rank2 both -> 0.5+0.5=1.0
]
st, body, raw = safe_request("POST", "/v2/vectordb/entities/insert", {"collectionName": COL, "data": rows})
if not (st == 200 and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — insert failed: %s" % raw[:300]); sys.exit(2)
st, _, raw = safe_request("POST", "/v2/vectordb/collections/load", {"collectionName": COL})
print("load:", st, raw[:100])
time.sleep(2)

st, body, raw = safe_request("POST", "/v2/vectordb/entities/hybrid_search", {
    "collectionName": COL,
    "search": [
        {"data": [[0.0] * 4], "annsField": "va", "limit": 3},
        {"data": [[0.0] * 4], "annsField": "vb", "limit": 3},
    ],
    "rerank": {"strategy": "rrf", "params": {"k": 4}},
    "limit": 3,
})
print("hybrid rrf:", st, raw[:400])
if not (st == 200 and isinstance(body, dict) and body.get("code") == 0):
    print("VERDICT: SCRIPT_ERROR — hybrid_search failed: %s" % raw[:300]); sys.exit(2)

ids = [r.get("id") for r in body.get("data", [])]
# expected: 101 and 102 tie at 1.2 (either order), 103 last at 1.0
ok = (sorted(ids[:2]) == [101, 102]) and (ids[2:3] == [103]) and len(ids) == 3
if not ok:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — RRF ordering wrong: expected [101,102]>(tie) [103], got %s" % ids)
    sys.exit(1)
print("VERDICT: NO_DEFECT")
