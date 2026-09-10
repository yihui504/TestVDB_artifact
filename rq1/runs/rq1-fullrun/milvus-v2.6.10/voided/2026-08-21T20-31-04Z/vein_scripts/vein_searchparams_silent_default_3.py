"""
vein_searchparams_silent_default: searchParams passthrough (utils.go:2076
generateSearchParams — REST layer does not validate) silently accepts invalid ef
values: negative int, 0, float 16.7, boolean true, string "16" — all return
code:0 with default-ef results, no warning or error. Control comparison shows
identical result sets across all invalid variants = value silently dropped.
"""
import os, time
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL", "http://localhost:19530").rstrip("/")
HEADERS = {"Authorization": "Bearer root:Milvus", "Content-Type": "application/json"}
COLL = "vein_sp_3"
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
    "data": [{"id": i, "vec": [float(i), 1.0, 0.0, 0.0]} for i in range(20)]})
time.sleep(2)

Q = {"collectionName": COLL, "data": [[0, 1, 0, 0]], "limit": 5}

# control: valid ef
st, base, _ = safe_request("POST", "/v2/vectordb/entities/search", {**Q, "searchParams": {"ef": 16}})
check("control_valid_ef", isinstance(base, dict) and base.get("code") == 0, base)

variants = {"neg": -1, "zero": 0, "float": 16.7, "bool": True, "str": "16", "bigint": 10**12}
for name, v in variants.items():
    st, body, _ = safe_request("POST", "/v2/vectordb/entities/search", {**Q, "searchParams": {"ef": v}})
    ok_silent = isinstance(body, dict) and body.get("code") == 0
    check(f"ef_{name}_silent_code0", ok_silent, body)
    if ok_silent:
        check(f"ef_{name}_same_as_default",
              [d.get("id") for d in body.get("data", [])] == [d.get("id") for d in base.get("data", [])],
              "invalid ef silently ignored, results identical to default")

try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COLL})
except Exception:
    pass

silent = sum(1 for p in PASS if p.endswith("_silent_code0"))
print(f"\nVERDICT: {'DEFECT_FOUND' if silent >= 5 else 'NO_DEFECT'} "
      f"({len(PASS)} pass / {len(FAIL)} fail) — {silent}/6 invalid ef values silently accepted with code:0")
