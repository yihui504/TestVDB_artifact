"""Shared helper for milvus v2.6.17 attack scripts (contract-driven)."""
import json, os, sys, time
import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL", "http://localhost:19530")
HEADERS = {"Authorization": "Bearer root:Milvus", "Content-Type": "application/json"}
API = BASE_URL.rstrip("/") + "/v2/vectordb/"


def safe_request(method, path_key, payload=None, timeout=60):
    url = API + path_key.replace("+", "/")
    try:
        r = requests.request(method, url, headers=HEADERS,
                             data=json.dumps(payload) if payload is not None else None,
                             timeout=timeout)
        raw = r.text
        try:
            body = r.json()
        except Exception:
            body = None
        return r.status_code, body, raw
    except Exception as e:
        return -1, None, "EXC: %s" % e


def code_of(body):
    if isinstance(body, dict):
        try:
            return int(body.get("code"))
        except Exception:
            return None
    return None


def create_collection(name, dim=8, with_array=True, array_field="tags"):
    """Full-schema create with Array field + FLAT vector index (2.6: load requires index)."""
    fields = [
        {"fieldName": "id", "dataType": "Int64", "isPrimary": True, "elementTypeParams": {}},
        {"fieldName": "vector", "dataType": "FloatVector", "elementTypeParams": {"dim": str(dim)}},
    ]
    if with_array:
        fields.append({"fieldName": array_field, "dataType": "Array", "elementDataType": "VarChar",
                       "elementTypeParams": {"max_capacity": "4096", "max_length": "64"}})
    s, b, raw = safe_request("POST", "collections+create", {
        "collectionName": name, "schema": {"autoID": False, "enableDynamicField": True, "fields": fields}})
    if code_of(b) != 0:
        return s, b, raw
    s, b, raw = safe_request("POST", "indexes+create", {
        "collectionName": name,
        "indexParams": [{"fieldName": "vector", "indexName": "vector_idx",
                         "indexType": "FLAT", "metricType": "L2"}]})
    return s, b, raw


def load_collection(name, retries=6):
    last = None
    for _ in range(retries):
        s, b, raw = safe_request("POST", "collections+load", {"collectionName": name})
        last = (s, b, raw)
        if code_of(b) == 0:
            return s, b, raw
        time.sleep(0.5)
    return last


def drop_collection(name):
    try:
        safe_request("POST", "collections+drop", {"collectionName": name})
    except Exception:
        pass


def query_all(name, filter_expr="id >= 0", output_fields=None):
    p = {"collectionName": name, "filter": filter_expr, "limit": 100,
         "consistencyLevel": "Strong"}
    if output_fields:
        p["outputFields"] = output_fields
    return safe_request("POST", "entities+query", p)


def unwrap_array_field(v):
    """Normalize leaked proto Array wrapper {'Data':{'StringData':{'data':[..]}}} -> list."""
    if isinstance(v, dict) and "Data" in v:
        inner = v["Data"]
        if isinstance(inner, dict):
            for k in ("StringData", "LongData", "BoolData", "DoubleData", "IntData",
                      "FloatData", "Data"):
                if k in inner and isinstance(inner[k], dict) and "data" in inner[k]:
                    return inner[k]["data"]
    return v


def get_stats(name):
    s, b, raw = safe_request("POST", "collections+get_stats", {"collectionName": name})
    rc = ((b or {}).get("data") or {}).get("rowCount")
    return code_of(b), rc, raw
