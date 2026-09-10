# Attack: v1 vs v2 semantics divergence (autoID policy + metricType default) + search type coercion
# contracts milvus_bc_v1_vs_v2_semantics + milvus_state_insert_001 + milvus_type_create_collection_001
# source: https://github.com/milvus-io/milvus/blob/v2.3.22/internal/distributed/proxy/httpserver/handler_v2.go doc_version v2.3.22
import os, sys, time, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set"); sys.exit(2)
H = {"Content-Type": "application/json", "Authorization": "Bearer root:Milvus"}
DIM = 4
COL1 = "testvdb_sem_v1auto_06"
COL2 = "testvdb_sem_v2quick_06"

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

for c in (COL1, COL2): drop(c)
defects = []

# --- Part A: v1 quick-create forces autoID=true ---
s, b, r = safe_request("POST", "/v1/vector/collections/create", json={"collectionName": COL1, "dimension": DIM})
print("v1_create:", s, r[:200])
if not (s == 200 and ok(b)):
    print("VERDICT: SCRIPT_ERROR - v1 create failed"); sys.exit(2)

# explicit id -> must be rejected 1804
s, b, r = safe_request("POST", "/v1/vector/insert",
    json={"collectionName": COL1, "data": [{"id": 100, "vector": [0.1]*DIM}]})
print("v1_insert_id:", s, r[:300])
code = b.get("code") if isinstance(b, dict) else None
if s == 200 and code == 200:
    defects.append("v1 insert with explicit id on autoID collection accepted (Type1_IllegalSuccess)")
else:
    msg = str(b.get("message", "")).lower() if isinstance(b, dict) else ""
    if "autoid" not in msg and "primary key" not in msg and "auto" not in msg:
        defects.append(f"autoID rejection msg lacks cause: {msg!r} (Type2_PoorDiagnostics)")

# no id -> success with insertIds
s, b, r = safe_request("POST", "/v1/vector/insert",
    json={"collectionName": COL1, "data": [{"vector": [0.1]*DIM}]})
print("v1_insert:", s, r[:300])
if not (s == 200 and ok(b)):
    defects.append("v1 insert without id failed despite autoID=true")
elif "insertIds" not in (b.get("data") or {}) and "insertIds" not in b:
    defects.append(f"insert success missing insertIds: {r[:200]} (Type2)")

# --- Part B: v2 quick-create default metric should be COSINE per contract ---
s, b, r = safe_request("POST", "/v2/vectordb/collections/create", json={"collectionName": COL2, "dimension": DIM})
print("v2_create:", s, r[:200])
if not (s == 200 and ok(b)):
    print("VERDICT: SCRIPT_ERROR - v2 create failed"); sys.exit(2)
time.sleep(2)
s, b, r = safe_request("POST", "/v2/vectordb/indexes/list", json={"collectionName": COL2})
print("v2_index_list:", s, r[:400])
metric = None
if ok(b):
    items = b.get("data") or []
    if items:
        iname = items[0].get("indexName") if isinstance(items[0], dict) else items[0]
        s2, b2, r2 = safe_request("POST", "/v2/vectordb/indexes/describe",
            json={"collectionName": COL2, "indexName": iname})
        print("v2_index_describe:", s2, r2[:400])
        if ok(b2):
            d = b2.get("data")
            d = d[0] if isinstance(d, list) and d else d
            if isinstance(d, dict):
                metric = d.get("metricType")
else:
    defects.append("indexes/list failed on quick-created collection (Type3)")
print("metric:", metric)
if metric and metric != "COSINE":
    defects.append(f"v2 quick-create metric default {metric} != contract COSINE (Type4/BS-05 Documentation Drift)")

# --- Part C: search limit type coercion (string/float/bool) ---
s, b, r = safe_request("POST", "/v1/vector/search",
    json={"collectionName": COL1, "vector": [0.1]*DIM, "limit": "5"})
print("limit_str:", s, r[:200])
code = b.get("code") if isinstance(b, dict) else None
if s == 200 and code == 200:
    defects.append("string limit '5' accepted (Type1_IllegalSuccess)")

s, b, r = safe_request("POST", "/v1/vector/search",
    json={"collectionName": COL1, "vector": [0.1]*DIM, "limit": 5.5})
print("limit_float:", s, r[:200])
code = b.get("code") if isinstance(b, dict) else None
if s == 200 and code == 200:
    defects.append("float limit 5.5 accepted (Type1_IllegalSuccess)")

for c in (COL1, COL2): drop(c)
if defects:
    print("VERDICT: DEFECT_FOUND")
    for d in defects: print("-", d)
    sys.exit(1)
print("VERDICT: NO_DEFECT")
