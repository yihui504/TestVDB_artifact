"""
vein_v1_internal_path_leak: v1 legacy search (/v1/vector/search) with a wrong-dim
query vector returns an error message that leaks the internal build-tree source
path and code location:
  "at /workspace/source/internal/core/src/query/Plan.cpp:91"
plus internal byte-size arithmetic (expected 16, actual 12). Information
disclosure via error message on the legacy surface (handler_v1.go search path).
"""
import os, time
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL", "http://localhost:19530").rstrip("/")
HEADERS = {"Authorization": "Bearer root:Milvus", "Content-Type": "application/json"}
COLL = "vein_v1l_5"
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
    print(("PASS " if cond else "FAIL ") + name + " " + str(detail)[:200])


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
    "collectionName": COLL, "data": [{"id": i, "vec": [float(i), 1.0, 0.0, 0.0]} for i in range(5)]})
time.sleep(2)

# control: correct dim works
st, body, _ = safe_request("POST", "/v1/vector/search",
                           {"collectionName": COLL, "vector": [0, 1, 0, 0], "limit": 3})
check("control_v1_search_ok", isinstance(body, dict) and body.get("code") == 200, body)

# attack: wrong dim -> internal path leak
st, body, _ = safe_request("POST", "/v1/vector/search",
                           {"collectionName": COLL, "vector": [0, 1, 0], "limit": 3})
msg = body.get("message", "") if isinstance(body, dict) else ""
check("v1_wrong_dim_errors", isinstance(body, dict) and body.get("code") == 65535, body)
check("leaks_source_path", ".cpp:" in msg or "/workspace/source/" in msg, msg)
check("leaks_plan_location", "Plan.cpp" in msg, msg)

try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COLL})
except Exception:
    pass

leak = any(p == "leaks_source_path" for p in PASS)
print(f"\nVERDICT: {'DEFECT_FOUND' if leak else 'NO_DEFECT'} "
      f"({len(PASS)} pass / {len(FAIL)} fail) — build path + source location disclosure in v2.6 REST error")
