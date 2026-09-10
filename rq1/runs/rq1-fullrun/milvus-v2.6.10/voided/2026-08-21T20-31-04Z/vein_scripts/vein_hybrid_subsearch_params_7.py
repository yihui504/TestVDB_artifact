"""
vein_hybrid_subsearch_params: hybrid_search sub-search params passthrough accepts
a non-numeric ef ("abc") with code:0 and silently uses defaults (results
identical to a valid-ef control) — same silent-substitution shape as
entities/search searchParams but on the 2.6 hybrid path (advancedSearch ->
generateSearchParams, utils.go:2076). Cross-pollination: search vein applied to
hybrid_search endpoint.
"""
import os, time
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL", "http://localhost:19530").rstrip("/")
HEADERS = {"Authorization": "Bearer root:Milvus", "Content-Type": "application/json"}
COLL = "vein_hs_7"
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
    "collectionName": COLL, "data": [{"id": i, "vec": [float(i), 1.0, 0.0, 0.0]} for i in range(10)]})
time.sleep(2)

RERANK = {"strategy": "rrf", "params": {"k": 60}}

# control: valid params
st, base, _ = safe_request("POST", "/v2/vectordb/entities/hybrid_search", {
    "collectionName": COLL,
    "search": [{"data": [[0, 1, 0, 0]], "annsField": "vec", "limit": 5, "params": {"ef": 16}}],
    "rerank": RERANK, "limit": 5})
check("control_valid", isinstance(base, dict) and base.get("code") == 0, base)

# control: unknown rerank strategy errors 65535 (validation exists at rerank layer)
st, body, _ = safe_request("POST", "/v2/vectordb/entities/hybrid_search", {
    "collectionName": COLL,
    "search": [{"data": [[0, 1, 0, 0]], "annsField": "vec", "limit": 5}],
    "rerank": {"strategy": "bogus"}, "limit": 5})
check("control_bad_rerank_errors", isinstance(body, dict) and body.get("code") == 65535, body)

# attack: non-numeric ef in sub-search params silently accepted
st, body, _ = safe_request("POST", "/v2/vectordb/entities/hybrid_search", {
    "collectionName": COLL,
    "search": [{"data": [[0, 1, 0, 0]], "annsField": "vec", "limit": 5, "params": {"ef": "abc"}}],
    "rerank": RERANK, "limit": 5})
check("subsearch_ef_str_silent_code0", isinstance(body, dict) and body.get("code") == 0, body)
if isinstance(body, dict) and body.get("code") == 0:
    check("subsearch_ef_str_same_as_valid",
          [d.get("id") for d in body.get("data", [])] == [d.get("id") for d in base.get("data", [])],
          "identical to valid-ef results = silently substituted default")

# attack: negative ef
st, body, _ = safe_request("POST", "/v2/vectordb/entities/hybrid_search", {
    "collectionName": COLL,
    "search": [{"data": [[0, 1, 0, 0]], "annsField": "vec", "limit": 5, "params": {"ef": -3}}],
    "rerank": RERANK, "limit": 5})
check("subsearch_ef_neg_silent_code0", isinstance(body, dict) and body.get("code") == 0, body)

try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COLL})
except Exception:
    pass

silent = any(p == "subsearch_ef_str_silent_code0" for p in PASS)
print(f"\nVERDICT: {'DEFECT_FOUND' if silent else 'NO_DEFECT'} "
      f"({len(PASS)} pass / {len(FAIL)} fail) — hybrid sub-search params: rerank validated, ef silently substituted (asymmetric)")
