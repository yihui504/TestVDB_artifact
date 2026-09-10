# Attack: filter expression semantics + diagnosis quality for invalid filters
# Blindspot BS-02; contracts milvus_behavioral_query_001 + FilterExpr data_type
# source: https://github.com/milvus-io/milvus/blob/v2.3.22/internal/distributed/proxy/httpserver/handler_v1.go doc_version v2.3.22
import os, sys, time, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set"); sys.exit(2)
H = {"Content-Type": "application/json", "Authorization": "Bearer root:Milvus"}
DIM = 4
COL = "testvdb_sem_filter_05"

def safe_request(method, endpoint, json=None, timeout=20):
    try:
        r = requests.request(method, f"{BASE_URL}{endpoint}", json=json, headers=H, timeout=timeout)
        try: body = r.json()
        except Exception: body = r.text
        return r.status_code, body, r.text
    except Exception as e:
        return -1, str(e), str(e)

def ok(b): return isinstance(b, dict) and b.get("code") == 200

def drop(name):
    try: safe_request("POST", "/v2/vectordb/collections/drop", json={"collectionName": name})
    except Exception: pass

drop(COL)
schema = {"fields": [
    {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
    {"fieldName": "score", "dataType": "Int64"},
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
    {"id": 1, "score": 5,  "vector": [1.0, 0.0, 0.0, 0.0]},
    {"id": 2, "score": 15, "vector": [0.9, 0.1, 0.0, 0.0]},
    {"id": 3, "score": 25, "vector": [0.0, 5.0, 0.0, 0.0]},
]
s, b, r = safe_request("POST", "/v2/vectordb/entities/insert", json={"collectionName": COL, "data": data})
print("insert:", s, r[:200])
time.sleep(3)

defects = []

def query(filter_, limit=10):
    return safe_request("POST", "/v2/vectordb/entities/query",
        json={"collectionName": COL, "filter": filter_, "limit": limit, "outputFields": ["id", "score"]})

# 1. eq filter
s, b, r = query("score == 15")
print("eq15:", s, r[:300])
ids = sorted([h.get("id") for h in (b.get("data") or [])]) if ok(b) else None
if ids != [2]:
    defects.append(f"score == 15 returned {ids}, expected [2] (Type4_StateLogicViolation)")

# 2. range filter
s, b, r = query("score > 10 and score < 26")
print("range:", s, r[:300])
ids = sorted([h.get("id") for h in (b.get("data") or [])]) if ok(b) else None
if ids != [2, 3]:
    defects.append(f"range filter returned {ids}, expected [2,3] (Type4)")

# 3. in filter
s, b, r = query("score in [5, 25]")
print("in:", s, r[:300])
ids = sorted([h.get("id") for h in (b.get("data") or [])]) if ok(b) else None
if ids != [1, 3]:
    defects.append(f"in filter returned {ids}, expected [1,3] (Type4)")

# 4. invalid filter -> must be rejected with diagnostic message naming the expr
s, b, r = query("score >>> 5")
print("invalid_filter:", s, r[:400])
if isinstance(b, dict) and b.get("code") == 65535:
    defects.append("invalid filter expr -> code 65535 (unexpected), contract milvus_behavioral_query_001 says 1804-family (BS-05 Documentation Drift)")
code = b.get("code") if isinstance(b, dict) else None
if s == 200 and code == 200:
    defects.append("invalid filter 'score >>> 5' accepted, returned rows (Type1_IllegalSuccess)")
elif code not in (1804, 1800, 65535):
    defects.append(f"invalid filter rejected with code {code}, contract says 1804-family (Type2/BS-05)")
else:
    msg = str(b.get("message", "")).lower() if isinstance(b, dict) else str(b).lower()
    score_diag = 0
    if any(k in msg for k in ("filter", "expr", "expression", "score")): score_diag += 1
    if any(k in msg for k in ("syntax", "invalid", "unexpected", "cannot", "expect", "error")): score_diag += 1
    if score_diag == 0:
        defects.append(f"invalid-filter error msg lacks expr/diagnosis info: {msg!r} (Type2_PoorDiagnostics)")

# 5. filter on nonexistent field
s, b, r = query("nonexistent_field == 1")
print("bad_field:", s, r[:300])
code = b.get("code") if isinstance(b, dict) else None
if s == 200 and code == 200:
    defects.append("filter on nonexistent field silently accepted (Type1_IllegalSuccess)")

# 6. search+filter combination semantics
s, b, r = safe_request("POST", "/v2/vectordb/entities/search",
    json={"collectionName": COL, "data": [[1.0, 0.0, 0.0, 0.0]], "limit": 10, "filter": "score >= 15", "outputFields": ["id"]})
print("search_filter:", s, r[:300])
if ok(b):
    ids = sorted([h.get("id") for h in (b.get("data") or [])])
    if ids != [2, 3]:
        defects.append(f"search with filter score>=15 returned {ids}, expected [2,3] (Type4)")
else:
    defects.append("search+filter on valid collection failed")

drop(COL)
if defects:
    print("VERDICT: DEFECT_FOUND")
    for d in defects: print("-", d)
    sys.exit(1)
print("VERDICT: NO_DEFECT")
