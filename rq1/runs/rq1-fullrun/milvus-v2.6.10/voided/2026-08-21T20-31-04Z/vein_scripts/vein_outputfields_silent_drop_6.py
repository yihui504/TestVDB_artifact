"""
vein_outputfields_silent_drop: on enableDynamicField=true collections,
entities/query with an unknown field in outputFields silently returns rows
without that field (code:0, no error, no field). Control: the identical
unknown name on a dynamic-disabled collection errors 65535 "field X not
exist"; the identical name in `filter` errors 1100. So on dynamic collections
the field-existence contract for outputFields is silently skipped.
Root cause: same dynamic-JSON fallback (typeutil/schema.go:468) as the filter
vein, but on the outputFields path there is no schema validation at all.
"""
import os, time
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL", "http://localhost:19530").rstrip("/")
HEADERS = {"Authorization": "Bearer root:Milvus", "Content-Type": "application/json"}
COLL = "vein_of_6"          # dynamic-enabled
COLL_ND = "vein_of_6n"      # dynamic-disabled control
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


def build(coll, dynamic):
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": coll})
    time.sleep(1)
    safe_request("POST", "/v2/vectordb/collections/create", {
        "collectionName": coll,
        "schema": {"enableDynamicField": dynamic, "fields": [
            {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
            {"fieldName": "vec", "dataType": "FloatVector", "elementTypeParams": {"dim": 4}},
            {"fieldName": "val", "dataType": "Int64"},
        ]},
        "indexParams": [{"fieldName": "vec", "indexName": "vi", "metricType": "L2",
                         "params": {"index_type": "HNSW", "M": 8, "efConstruction": 64}}],
    })
    time.sleep(3)
    safe_request("POST", "/v2/vectordb/collections/load", {"collectionName": coll})
    time.sleep(2)
    safe_request("POST", "/v2/vectordb/entities/insert", {
        "collectionName": coll,
        "data": [{"id": i, "vec": [float(i), 1.0, 0.0, 0.0], "val": i} for i in range(5)]})
    time.sleep(2)


build(COLL, True)
build(COLL_ND, False)

# control 1: valid outputFields on dyn collection
st, body, _ = safe_request("POST", "/v2/vectordb/entities/query",
                           {"collectionName": COLL, "filter": "id == 1", "outputFields": ["val"],
                            "consistencyLevel": "Strong"})
check("control_valid_output", isinstance(body, dict) and body.get("code") == 0
      and "val" in (body.get("data") or [{}])[0], body)

# control 2: identical unknown outputField on no-dyn collection errors 65535
st, body, _ = safe_request("POST", "/v2/vectordb/entities/query",
                           {"collectionName": COLL_ND, "filter": "id == 1", "outputFields": ["nope_field"],
                            "consistencyLevel": "Strong"})
check("control_nodyn_output_errors", isinstance(body, dict) and body.get("code") == 65535, body)

# control 3: identical unknown name in filter errors 1100
st, body, _ = safe_request("POST", "/v2/vectordb/entities/query",
                           {"collectionName": COLL, "filter": "nope_field == 1", "limit": 1})
check("control_filter_unknown_errors", isinstance(body, dict) and body.get("code") == 1100, body)

# attack: unknown outputField on dyn collection silently dropped
st, body, _ = safe_request("POST", "/v2/vectordb/entities/query",
                           {"collectionName": COLL, "filter": "id == 1", "outputFields": ["nope_field"],
                            "consistencyLevel": "Strong"})
check("dyn_output_unknown_silent_code0", isinstance(body, dict) and body.get("code") == 0, body)
if isinstance(body, dict) and body.get("code") == 0:
    row = (body.get("data") or [{}])[0]
    check("unknown_field_missing_no_error", bool(body.get("data")) and "nope_field" not in row, row)

# attack variant: mixed valid+invalid silently partial
st, body, _ = safe_request("POST", "/v2/vectordb/entities/query",
                           {"collectionName": COLL, "filter": "id == 1", "outputFields": ["val", "nope2"],
                            "consistencyLevel": "Strong"})
row = (body.get("data") or [{}])[0] if isinstance(body, dict) else {}
check("mixed_output_partial_silent", isinstance(body, dict) and body.get("code") == 0
      and "val" in row and "nope2" not in row, row)

for c in (COLL, COLL_ND):
    try:
        safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": c})
    except Exception:
        pass

silent = any(p == "dyn_output_unknown_silent_code0" for p in PASS)
print(f"\nVERDICT: {'DEFECT_FOUND' if silent else 'NO_DEFECT'} "
      f"({len(PASS)} pass / {len(FAIL)} fail) — dyn-collection outputFields unknown silently dropped "
      f"(no-dyn errors 65535; filter errors 1100; asymmetric validation)")
