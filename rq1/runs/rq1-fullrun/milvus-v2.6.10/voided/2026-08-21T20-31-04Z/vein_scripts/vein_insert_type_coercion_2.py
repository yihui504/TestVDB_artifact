"""
vein_insert_type_coercion: entities/insert with a VarChar value ("5") for an Int64
schema field is accepted (code:0) and silently coerced to int 5 on read-back.
Control: Float field with bool value is rejected 1804 — so coercion is inconsistent
per-type: Int64 column accepts strings, Float column rejects bools.
Source: internal/distributed/proxy/httpserver/utils.go appendInsertFieldData path.
"""
import os, time
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL", "http://localhost:19530").rstrip("/")
HEADERS = {"Authorization": "Bearer root:Milvus", "Content-Type": "application/json"}
COLL = "vein_tc_2"
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
st, body, _ = safe_request("POST", "/v2/vectordb/collections/create", {
    "collectionName": COLL,
    "schema": {"enableDynamicField": False, "fields": [
        {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
        {"fieldName": "vec", "dataType": "FloatVector", "elementTypeParams": {"dim": 4}},
        {"fieldName": "val", "dataType": "Int64"},
        {"fieldName": "score", "dataType": "Float"},
    ]},
    "indexParams": [{"fieldName": "vec", "indexName": "vi", "metricType": "L2",
                     "params": {"index_type": "HNSW", "M": 8, "efConstruction": 64}}],
})
time.sleep(3)
safe_request("POST", "/v2/vectordb/collections/load", {"collectionName": COLL})
time.sleep(2)

# control: valid insert works
st, body, _ = safe_request("POST", "/v2/vectordb/entities/insert", {
    "collectionName": COLL, "data": [{"id": 1, "vec": [1.0, 0, 0, 0], "val": 1, "score": 1.0}]})
check("control_valid_insert", isinstance(body, dict) and body.get("code") == 0, body)

# control: wrong-type rejected for Float (bool)
st, body, _ = safe_request("POST", "/v2/vectordb/entities/insert", {
    "collectionName": COLL, "data": [{"id": 2, "vec": [1.0, 0, 0, 0], "val": 2, "score": True}]})
check("control_float_bool_rejected", isinstance(body, dict) and body.get("code") == 1804, body)

# attack: string value for Int64 field
st, body, _ = safe_request("POST", "/v2/vectordb/entities/insert", {
    "collectionName": COLL, "data": [{"id": 3, "vec": [1.0, 0, 0, 0], "val": "5", "score": 1.0}]})
check("int64_string_accepted", isinstance(body, dict) and body.get("code") == 0, body)

time.sleep(2)
safe_request("POST", "/v2/vectordb/collections/flush", {"collectionName": COLL})
time.sleep(3)
st, body, _ = safe_request("POST", "/v2/vectordb/entities/get", {"collectionName": COLL, "id": 3})
row = (body.get("data") or [{}])[0] if isinstance(body, dict) else {}
check("coerced_readback", row.get("val") == 5 and not isinstance(row.get("val"), str), row)

# variant: bool for Int64
st, body, _ = safe_request("POST", "/v2/vectordb/entities/insert", {
    "collectionName": COLL, "data": [{"id": 4, "vec": [1.0, 0, 0, 0], "val": True, "score": 1.0}]})
check("int64_bool_rejected_control", isinstance(body, dict) and body.get("code") == 1804, body)

try:
    safe_request("POST", "/v2/vectordb/collections/drop", {"collectionName": COLL})
except Exception:
    pass

silent = any(p == "int64_string_accepted" for p in PASS)
print(f"\nVERDICT: {'DEFECT_FOUND' if silent else 'NO_DEFECT'} "
      f"({len(PASS)} pass / {len(FAIL)} fail) — Type2 silent coercion of \"5\"->5 into Int64 column")
